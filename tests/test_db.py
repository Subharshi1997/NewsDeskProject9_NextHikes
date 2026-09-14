import pytest

import db
from providers.base import NormalizedArticle


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_news.db"
    monkeypatch.setenv("NEWS_DB_PATH", str(db_path))
    db.init_db()
    return db_path


def make_article(**overrides):
    defaults = dict(
        article_id="1", title="Title", url="https://example.com/a", provider="p",
        source_name="Reuters", canonical_url="https://example.com/a",
        is_duplicate=False, quality_score=0.8, is_primary=True,
    )
    defaults.update(overrides)
    return NormalizedArticle(**defaults)


def test_store_articles_inserts_non_duplicates(temp_db):
    a1 = make_article(title="Story A", url="https://example.com/a", canonical_url="https://example.com/a")
    a2 = make_article(title="Story B", url="https://example.com/b", canonical_url="https://example.com/b", article_id="2")

    inserted, skipped = db.store_articles([a1, a2])

    assert inserted == 2
    assert skipped == 0
    assert len(db.get_articles(limit=10)) == 2


def test_store_articles_skips_flagged_duplicates(temp_db):
    a1 = make_article(title="Story A", url="https://example.com/a", canonical_url="https://example.com/a")
    a2 = make_article(
        title="Story A dup", url="https://example.com/a-alt", canonical_url="https://example.com/a",
        article_id="2", is_duplicate=True,
    )

    inserted, skipped = db.store_articles([a1, a2])

    assert inserted == 1
    assert skipped == 1
    assert len(db.get_articles(limit=10)) == 1


def test_store_articles_enforces_unique_canonical_url_at_db_level(temp_db):
    # Both marked non-duplicate at the Python layer -- the DB's UNIQUE
    # constraint on canonical_url is the defense-in-depth backstop.
    a1 = make_article(title="Story A", url="https://example.com/a", canonical_url="https://example.com/a")
    a2 = make_article(title="Story A again", url="https://example.com/a", canonical_url="https://example.com/a", article_id="2")

    inserted, skipped = db.store_articles([a1, a2])

    assert inserted == 1
    assert skipped == 1


def test_get_articles_filters_by_category(temp_db):
    a1 = make_article(title="Biz story", url="https://example.com/a", canonical_url="https://example.com/a", category="business")
    a2 = make_article(
        title="Tech story", url="https://example.com/b", canonical_url="https://example.com/b",
        article_id="2", category="technology",
    )
    db.store_articles([a1, a2])

    rows = db.get_articles(category="business")

    assert len(rows) == 1
    assert rows[0]["title"] == "Biz story"


def test_get_stories_aggregates_source_names_and_article_count(temp_db):
    a1 = make_article(
        title="Story", url="https://a.example.com/1", canonical_url="https://a.example.com/1",
        source_name="Reuters", story_id="story-1",
    )
    a2 = make_article(
        title="Story", url="https://b.example.com/2", canonical_url="https://b.example.com/2",
        article_id="2", source_name="BBC", story_id="story-1",
    )
    db.store_articles([a1, a2])

    stories = db.get_stories()

    assert len(stories) == 1
    assert stories[0]["article_count"] == 2
    assert set(stories[0]["source_names"]) == {"Reuters", "BBC"}


def test_get_stories_includes_extras_columns(temp_db):
    a1 = make_article(title="Story", url="https://example.com/a", canonical_url="https://example.com/a", story_id="story-1")
    db.store_articles(
        [a1],
        story_summaries={"story-1": "S"},
        story_extras={"story-1": {"timeline": "T", "coverage_comparison": "C", "why_matters": "W"}},
    )

    stories = db.get_stories()

    assert stories[0]["summary"] == "S"
    assert stories[0]["timeline"] == "T"
    assert stories[0]["coverage_comparison"] == "C"
    assert stories[0]["why_matters"] == "W"


def test_get_stories_filters_by_primary_article_sentiment(temp_db):
    primary = make_article(
        title="Story", url="https://a.example.com/1", canonical_url="https://a.example.com/1",
        story_id="story-1", is_primary=True, quality_score=0.9, sentiment="positive",
    )
    secondary = make_article(
        title="Story", url="https://b.example.com/2", canonical_url="https://b.example.com/2",
        article_id="2", story_id="story-1", is_primary=False, quality_score=0.4, sentiment="negative",
    )
    db.store_articles([secondary, primary])

    assert len(db.get_stories(sentiment="positive")) == 1
    assert len(db.get_stories(sentiment="negative")) == 0  # secondary's sentiment doesn't count


def test_get_stories_filters_by_category_and_source(temp_db):
    a1 = make_article(
        title="Business story", url="https://a.example.com/1", canonical_url="https://a.example.com/1",
        story_id="story-1", category="business", source_name="Reuters",
    )
    a2 = make_article(
        title="Sports story", url="https://b.example.com/2", canonical_url="https://b.example.com/2",
        article_id="2", story_id="story-2", category="sports", source_name="ESPN",
    )
    db.store_articles([a1, a2])

    business_only = db.get_stories(category="business")
    assert len(business_only) == 1
    assert business_only[0]["story_id"] == "story-1"

    reuters_only = db.get_stories(source_name="Reuters")
    assert len(reuters_only) == 1
    assert reuters_only[0]["story_id"] == "story-1"


def test_get_stories_filters_by_since(temp_db):
    old = make_article(
        title="Old story", url="https://a.example.com/1", canonical_url="https://a.example.com/1",
        story_id="story-1", published_at="2026-01-01T00:00:00+00:00",
    )
    recent = make_article(
        title="Recent story", url="https://b.example.com/2", canonical_url="https://b.example.com/2",
        article_id="2", story_id="story-2", published_at="2026-09-14T00:00:00+00:00",
    )
    db.store_articles([old, recent])

    result = db.get_stories(since="2026-06-01T00:00:00+00:00")

    assert len(result) == 1
    assert result[0]["story_id"] == "story-2"


def test_get_stories_still_aggregates_all_sources_when_filtered(temp_db):
    # The filter matches on the primary article, but source_names should
    # still reflect every article in the story, not just the primary one.
    primary = make_article(
        title="Story", url="https://a.example.com/1", canonical_url="https://a.example.com/1",
        story_id="story-1", is_primary=True, quality_score=0.9, category="business", source_name="Reuters",
    )
    secondary = make_article(
        title="Story", url="https://b.example.com/2", canonical_url="https://b.example.com/2",
        article_id="2", story_id="story-1", is_primary=False, quality_score=0.4, source_name="BBC",
    )
    db.store_articles([secondary, primary])

    result = db.get_stories(category="business")

    assert set(result[0]["source_names"]) == {"Reuters", "BBC"}


def test_get_story_articles_orders_primary_first(temp_db):
    primary = make_article(
        title="Story", url="https://a.example.com/1", canonical_url="https://a.example.com/1",
        story_id="story-1", is_primary=True, quality_score=0.9,
    )
    secondary = make_article(
        title="Story", url="https://b.example.com/2", canonical_url="https://b.example.com/2",
        article_id="2", story_id="story-1", is_primary=False, quality_score=0.4,
    )
    db.store_articles([secondary, primary])

    rows = db.get_story_articles("story-1")

    assert len(rows) == 2
    assert rows[0]["is_primary"] == 1


def test_store_articles_persists_sentiment(temp_db):
    a1 = make_article(
        title="Story A", url="https://example.com/a", canonical_url="https://example.com/a",
        sentiment="positive", sentiment_score=0.91,
    )
    db.store_articles([a1])

    rows = db.get_articles(sentiment="positive")

    assert len(rows) == 1
    assert rows[0]["sentiment_score"] == 0.91


def test_store_articles_links_entities(temp_db):
    a1 = make_article(
        title="Story A", url="https://example.com/a", canonical_url="https://example.com/a",
        entities=[{"text": "Nvidia", "label": "ORG"}, {"text": "Jensen Huang", "label": "PERSON"}],
    )
    db.store_articles([a1])

    rows = db.get_articles(limit=1)
    article_row_id = rows[0]["id"]
    linked = db.get_article_entities(article_row_id)

    assert {"entity_name": "Nvidia", "entity_type": "ORG"} in linked
    assert {"entity_name": "Jensen Huang", "entity_type": "PERSON"} in linked


def test_entities_not_linked_for_skipped_duplicates(temp_db):
    a1 = make_article(
        title="Story A", url="https://example.com/a", canonical_url="https://example.com/a",
        is_duplicate=True, entities=[{"text": "Nvidia", "label": "ORG"}],
    )
    db.store_articles([a1])

    with db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM article_entities").fetchone()[0]
    assert count == 0


def test_ensure_story_writes_summary_only_when_provided(temp_db):
    a1 = make_article(
        title="Story A", url="https://example.com/a", canonical_url="https://example.com/a",
        story_id="story-1",
    )
    db.store_articles([a1], story_summaries={"story-1": "A bullet-point summary."})

    story = db.get_story("story-1")
    assert story["summary"] == "A bullet-point summary."


def test_ensure_story_does_not_clobber_existing_summary(temp_db):
    a1 = make_article(
        title="Story A", url="https://example.com/a", canonical_url="https://example.com/a",
        story_id="story-1",
    )
    db.store_articles([a1], story_summaries={"story-1": "Original summary."})

    a2 = make_article(
        title="Story A", url="https://example.com/b", canonical_url="https://example.com/b",
        article_id="2", story_id="story-1",
    )
    db.store_articles([a2])  # no story_summaries this time

    story = db.get_story("story-1")
    assert story["summary"] == "Original summary."


def test_get_story_returns_none_for_unknown_story(temp_db):
    assert db.get_story("does-not-exist") is None


def test_get_story_sentiment_aggregates_counts_and_average(temp_db):
    a1 = make_article(
        title="Story", url="https://a.example.com/1", canonical_url="https://a.example.com/1",
        story_id="story-1", sentiment="positive", sentiment_score=0.9,
    )
    a2 = make_article(
        title="Story", url="https://b.example.com/2", canonical_url="https://b.example.com/2",
        article_id="2", story_id="story-1", sentiment="positive", sentiment_score=0.8,
    )
    a3 = make_article(
        title="Story", url="https://c.example.com/3", canonical_url="https://c.example.com/3",
        article_id="3", story_id="story-1", sentiment="negative", sentiment_score=0.7,
    )
    db.store_articles([a1, a2, a3])

    summary = db.get_story_sentiment("story-1")

    assert summary["positive"]["count"] == 2
    assert summary["positive"]["avg_score"] == pytest.approx(0.85)
    assert summary["negative"]["count"] == 1


def test_get_entity_activity_and_window_stats(temp_db):
    a1 = make_article(
        title="Story", url="https://a.example.com/1", canonical_url="https://a.example.com/1",
        source_name="Reuters", published_at="2026-09-15T10:00:00+00:00",
        entities=[{"text": "Nvidia", "label": "ORG"}],
    )
    a2 = make_article(
        title="Story2", url="https://b.example.com/2", canonical_url="https://b.example.com/2",
        article_id="2", source_name="BBC", published_at="2026-09-15T11:00:00+00:00",
        entities=[{"text": "Nvidia", "label": "ORG"}],
    )
    db.store_articles([a1, a2])

    activity = db.get_entity_activity(since="2026-09-01T00:00:00+00:00")
    assert ("Nvidia", "ORG") in activity

    stats = db.get_entity_window_stats("Nvidia", since="2026-09-01T00:00:00+00:00", until="2026-09-16T00:00:00+00:00")
    assert stats["count"] == 2
    assert stats["distinct_sources"] == 2
    assert stats["latest_published_at"] == "2026-09-15T11:00:00+00:00"


def test_get_entity_window_stats_returns_zero_for_no_activity(temp_db):
    stats = db.get_entity_window_stats("Nothing", since="2026-01-01T00:00:00+00:00", until="2026-01-02T00:00:00+00:00")
    assert stats == {"count": 0, "distinct_sources": 0, "latest_published_at": None}


# --- Phase 3: analytics aggregations ---

def test_get_article_count_with_and_without_since(temp_db):
    a1 = make_article(
        title="A", url="https://a.example.com/1", canonical_url="https://a.example.com/1",
        published_at="2026-09-10T00:00:00+00:00",
    )
    a2 = make_article(
        title="B", url="https://b.example.com/2", canonical_url="https://b.example.com/2",
        article_id="2", published_at="2026-09-01T00:00:00+00:00",
    )
    db.store_articles([a1, a2])

    assert db.get_article_count() == 2
    assert db.get_article_count(since="2026-09-05T00:00:00+00:00") == 1


def test_get_volume_by_day_groups_by_date(temp_db):
    a1 = make_article(
        title="A", url="https://a.example.com/1", canonical_url="https://a.example.com/1",
        published_at="2026-09-10T08:00:00+00:00",
    )
    a2 = make_article(
        title="B", url="https://b.example.com/2", canonical_url="https://b.example.com/2",
        article_id="2", published_at="2026-09-10T20:00:00+00:00",
    )
    db.store_articles([a1, a2])

    result = db.get_volume_by_day(days=30)

    assert result == [{"day": "2026-09-10", "count": 2}]


def test_get_top_categories_orders_by_count(temp_db):
    a1 = make_article(title="A", url="https://a.example.com/1", canonical_url="https://a.example.com/1", category="business")
    a2 = make_article(title="B", url="https://b.example.com/2", canonical_url="https://b.example.com/2", article_id="2", category="business")
    a3 = make_article(title="C", url="https://c.example.com/3", canonical_url="https://c.example.com/3", article_id="3", category="sports")
    db.store_articles([a1, a2, a3])

    result = db.get_top_categories()

    assert result[0] == {"category": "business", "count": 2}


def test_get_top_categories_splits_multi_value_fields(temp_db):
    # NewsData.io sometimes tags one article with multiple categories
    # joined into a single comma-separated field -- each should count
    # toward both categories, not form its own bogus compound bucket.
    a1 = make_article(title="A", url="https://a.example.com/1", canonical_url="https://a.example.com/1", category="top, politics")
    a2 = make_article(title="B", url="https://b.example.com/2", canonical_url="https://b.example.com/2", article_id="2", category="top")
    db.store_articles([a1, a2])

    result = db.get_top_categories()

    by_name = {r["category"]: r["count"] for r in result}
    assert by_name["top"] == 2
    assert by_name["politics"] == 1
    assert "top, politics" not in by_name


def test_get_top_sources_includes_averages(temp_db):
    a1 = make_article(
        title="A", url="https://a.example.com/1", canonical_url="https://a.example.com/1",
        source_name="Reuters", quality_score=0.8, sentiment_score=0.9,
    )
    a2 = make_article(
        title="B", url="https://b.example.com/2", canonical_url="https://b.example.com/2",
        article_id="2", source_name="Reuters", quality_score=0.6, sentiment_score=0.5,
    )
    db.store_articles([a1, a2])

    result = db.get_top_sources()

    assert result[0]["source_name"] == "Reuters"
    assert result[0]["article_count"] == 2
    assert result[0]["avg_quality"] == pytest.approx(0.7)


def test_get_country_field_counts_returns_raw_values(temp_db):
    a1 = make_article(title="A", url="https://a.example.com/1", canonical_url="https://a.example.com/1", country="IN")
    a2 = make_article(title="B", url="https://b.example.com/2", canonical_url="https://b.example.com/2", article_id="2", country="IN")
    db.store_articles([a1, a2])

    result = db.get_country_field_counts()

    assert ("IN", 2) in result


def test_get_sentiment_trend_by_day_groups_by_day_and_sentiment(temp_db):
    a1 = make_article(
        title="A", url="https://a.example.com/1", canonical_url="https://a.example.com/1",
        published_at="2026-09-10T00:00:00+00:00", sentiment="positive",
    )
    a2 = make_article(
        title="B", url="https://b.example.com/2", canonical_url="https://b.example.com/2",
        article_id="2", published_at="2026-09-10T00:00:00+00:00", sentiment="negative",
    )
    db.store_articles([a1, a2])

    result = db.get_sentiment_trend_by_day(days=30)

    by_sentiment = {r["sentiment"]: r["count"] for r in result}
    assert by_sentiment == {"positive": 1, "negative": 1}


def test_get_top_entities_orders_by_mention_count(temp_db):
    a1 = make_article(
        title="A", url="https://a.example.com/1", canonical_url="https://a.example.com/1",
        entities=[{"text": "Nvidia", "label": "ORG"}],
    )
    a2 = make_article(
        title="B", url="https://b.example.com/2", canonical_url="https://b.example.com/2",
        article_id="2", entities=[{"text": "Nvidia", "label": "ORG"}, {"text": "Rare Co", "label": "ORG"}],
    )
    db.store_articles([a1, a2])

    result = db.get_top_entities()

    assert result[0]["entity_name"] == "Nvidia"
    assert result[0]["mention_count"] == 2


def test_get_entity_top_sources_and_sentiment(temp_db):
    a1 = make_article(
        title="A", url="https://a.example.com/1", canonical_url="https://a.example.com/1",
        source_name="Reuters", sentiment="positive", sentiment_score=0.9,
        entities=[{"text": "Nvidia", "label": "ORG"}],
    )
    db.store_articles([a1])

    sources = db.get_entity_top_sources("Nvidia")
    sentiment = db.get_entity_sentiment("Nvidia")

    assert sources == [{"source_name": "Reuters", "count": 1}]
    assert sentiment["positive"]["count"] == 1


def test_get_entity_volume_by_day(temp_db):
    a1 = make_article(
        title="A", url="https://a.example.com/1", canonical_url="https://a.example.com/1",
        published_at="2026-09-10T00:00:00+00:00", entities=[{"text": "Nvidia", "label": "ORG"}],
    )
    db.store_articles([a1])

    result = db.get_entity_volume_by_day("Nvidia", days=30)

    assert result == [{"day": "2026-09-10", "count": 1}]


# --- Story extras (timeline / coverage comparison / why this matters) ---

def test_store_articles_writes_story_extras(temp_db):
    a1 = make_article(title="Story", url="https://example.com/a", canonical_url="https://example.com/a", story_id="story-1")
    db.store_articles(
        [a1],
        story_extras={"story-1": {"timeline": "T", "coverage_comparison": "C", "why_matters": "W"}},
    )

    story = db.get_story("story-1")
    assert story["timeline"] == "T"
    assert story["coverage_comparison"] == "C"
    assert story["why_matters"] == "W"


def test_store_articles_does_not_clobber_existing_extras(temp_db):
    a1 = make_article(title="Story", url="https://example.com/a", canonical_url="https://example.com/a", story_id="story-1")
    db.store_articles([a1], story_extras={"story-1": {"why_matters": "Original"}})

    a2 = make_article(
        title="Story", url="https://example.com/b", canonical_url="https://example.com/b",
        article_id="2", story_id="story-1",
    )
    db.store_articles([a2])  # no story_extras this time

    story = db.get_story("story-1")
    assert story["why_matters"] == "Original"


def test_set_story_extras_only_updates_provided_fields(temp_db):
    with db.get_connection() as conn:
        db.ensure_story(conn, "story-1", "Title")
        db.set_story_extras(conn, "story-1", why_matters="Only this")

    story = db.get_story("story-1")
    assert story["why_matters"] == "Only this"
    assert story["timeline"] is None


def test_set_story_extras_with_no_fields_is_a_noop(temp_db):
    with db.get_connection() as conn:
        db.ensure_story(conn, "story-1", "Title")
        db.set_story_extras(conn, "story-1")  # nothing to set

    story = db.get_story("story-1")
    assert story["why_matters"] is None


def test_set_story_extras_writes_coverage_perspective(temp_db):
    with db.get_connection() as conn:
        db.ensure_story(conn, "story-1", "Title")
        db.set_story_extras(conn, "story-1", coverage_perspective="Perspective text")

    story = db.get_story("story-1")
    assert story["coverage_perspective"] == "Perspective text"


# --- Story ordering, lookup by id, related stories ---

def test_get_stories_orders_by_quality_score(temp_db):
    low = make_article(
        title="Low quality", url="https://a.example.com/1", canonical_url="https://a.example.com/1",
        story_id="story-low", quality_score=0.2,
    )
    high = make_article(
        title="High quality", url="https://b.example.com/2", canonical_url="https://b.example.com/2",
        article_id="2", story_id="story-high", quality_score=0.9,
    )
    db.store_articles([low, high])

    result = db.get_stories(order_by="quality_score")

    assert result[0]["story_id"] == "story-high"
    assert result[0]["primary_quality_score"] == 0.9


def test_get_stories_includes_image_and_category(temp_db):
    a1 = make_article(
        title="Story", url="https://a.example.com/1", canonical_url="https://a.example.com/1",
        story_id="story-1", image_url="https://img.example.com/1.jpg", category="business",
    )
    db.store_articles([a1])

    result = db.get_stories()

    assert result[0]["image_url"] == "https://img.example.com/1.jpg"
    assert result[0]["primary_category"] == "business"


def test_get_stories_by_ids_returns_matching_stories_only(temp_db):
    a1 = make_article(title="A", url="https://a.example.com/1", canonical_url="https://a.example.com/1", story_id="story-1")
    a2 = make_article(title="B", url="https://b.example.com/2", canonical_url="https://b.example.com/2", article_id="2", story_id="story-2")
    db.store_articles([a1, a2])

    result = db.get_stories_by_ids(["story-1"])

    assert len(result) == 1
    assert result[0]["story_id"] == "story-1"


def test_get_stories_by_ids_empty_list_returns_empty(temp_db):
    assert db.get_stories_by_ids([]) == []


def test_get_related_stories_ranks_by_shared_entities(temp_db):
    a1 = make_article(
        title="Story A", url="https://a.example.com/1", canonical_url="https://a.example.com/1",
        story_id="story-a", entities=[{"text": "Nvidia", "label": "ORG"}, {"text": "AI", "label": "ORG"}],
    )
    a2 = make_article(
        title="Story B", url="https://b.example.com/2", canonical_url="https://b.example.com/2",
        article_id="2", story_id="story-b", entities=[{"text": "Nvidia", "label": "ORG"}, {"text": "AI", "label": "ORG"}],
    )
    a3 = make_article(
        title="Story C", url="https://c.example.com/3", canonical_url="https://c.example.com/3",
        article_id="3", story_id="story-c", entities=[{"text": "Nvidia", "label": "ORG"}],
    )
    db.store_articles([a1, a2, a3])

    related = db.get_related_stories("story-a")

    assert related[0]["story_id"] == "story-b"  # shares 2 entities
    assert related[0]["shared_entities"] == 2
    assert related[1]["story_id"] == "story-c"  # shares 1 entity
    assert "story-a" not in {r["story_id"] for r in related}


def test_get_related_stories_no_shared_entities_returns_empty(temp_db):
    a1 = make_article(
        title="Story A", url="https://a.example.com/1", canonical_url="https://a.example.com/1",
        story_id="story-a", entities=[{"text": "Nvidia", "label": "ORG"}],
    )
    a2 = make_article(
        title="Story B", url="https://b.example.com/2", canonical_url="https://b.example.com/2",
        article_id="2", story_id="story-b", entities=[{"text": "Unrelated", "label": "ORG"}],
    )
    db.store_articles([a1, a2])

    assert db.get_related_stories("story-a") == []
