from datetime import datetime, timedelta, timezone

import pytest

from pipeline.scoring import (
    SourceScorer,
    completeness_score,
    entity_importance_score,
    originality_score,
    recency_score,
    select_primary,
    source_diversity_score,
)
from providers.base import NormalizedArticle


def make_article(**overrides):
    defaults = dict(article_id="1", title="Title", url="https://example.com/a", provider="p", source_name="Source")
    defaults.update(overrides)
    return NormalizedArticle(**defaults)


def test_source_scorer_exact_match_is_case_insensitive(tmp_path):
    sources_file = tmp_path / "sources.json"
    sources_file.write_text(
        '{"default_quality_score": 2, "sources": [{"source_name": "Reuters", "quality_score": 5}]}',
        encoding="utf-8",
    )
    scorer = SourceScorer(sources_file=sources_file)
    assert scorer.score("Reuters") == 5
    assert scorer.score("reuters") == 5


def test_source_scorer_fuzzy_match(tmp_path):
    sources_file = tmp_path / "sources.json"
    sources_file.write_text(
        '{"default_quality_score": 2, "sources": [{"source_name": "BBC", "quality_score": 5}]}',
        encoding="utf-8",
    )
    scorer = SourceScorer(sources_file=sources_file)
    assert scorer.score("BBC News") == 5


def test_source_scorer_default_for_unknown_source(tmp_path):
    sources_file = tmp_path / "sources.json"
    sources_file.write_text('{"default_quality_score": 2, "sources": []}', encoding="utf-8")
    scorer = SourceScorer(sources_file=sources_file)
    assert scorer.score("Random Blog") == 2
    assert scorer.score(None) == 2


def test_recency_score_decays_with_age():
    now = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
    fresh = recency_score(now.isoformat(), now=now)
    twelve_hours_old = recency_score((now - timedelta(hours=12)).isoformat(), now=now)
    assert fresh == pytest.approx(1.0)
    assert twelve_hours_old == pytest.approx(0.5, abs=0.01)


def test_recency_score_missing_or_bad_date_is_zero():
    assert recency_score(None) == 0.0
    assert recency_score("not-a-date") == 0.0


def test_completeness_score_counts_populated_fields():
    full = make_article(description="d", content="c", image_url="i", author="a")
    empty = make_article()
    assert completeness_score(full) == 1.0
    assert completeness_score(empty) < completeness_score(full)


def test_originality_score_rewards_earliest_publisher():
    now = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
    first = make_article(title="A", published_at=(now - timedelta(hours=2)).isoformat())
    second = make_article(title="A", published_at=now.isoformat(), article_id="2", url="https://example.com/b")
    cluster = [first, second]
    assert originality_score(first, cluster) > originality_score(second, cluster)


def test_select_primary_picks_highest_scoring_article(tmp_path):
    sources_file = tmp_path / "sources.json"
    sources_file.write_text(
        '{"default_quality_score": 2, "sources": ['
        '{"source_name": "Reuters", "quality_score": 5}, '
        '{"source_name": "Random Blog", "quality_score": 1}]}',
        encoding="utf-8",
    )
    scorer = SourceScorer(sources_file=sources_file)
    now = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)

    reuters = make_article(
        title="Story", source_name="Reuters", description="d", content="c",
        published_at=now.isoformat(),
    )
    blog = make_article(
        title="Story", source_name="Random Blog", url="https://blog.example.com/1",
        article_id="2", published_at=now.isoformat(),
    )

    best = select_primary([reuters, blog], source_scorer=scorer, now=now)

    assert best is reuters
    assert reuters.is_primary is True
    assert blog.is_primary is False


def test_source_diversity_score_scales_with_distinct_sources():
    one_source = [make_article(source_name="Reuters")]
    five_sources = [make_article(source_name=name, article_id=name) for name in ["a", "b", "c", "d", "e"]]

    assert source_diversity_score(one_source) == pytest.approx(1 / 5)
    assert source_diversity_score(five_sources) == 1.0


def test_source_diversity_score_ignores_duplicate_source_names():
    same_source_twice = [make_article(source_name="Reuters"), make_article(source_name="Reuters", article_id="2")]
    assert source_diversity_score(same_source_twice) == pytest.approx(1 / 5)


def test_source_diversity_score_empty_list():
    assert source_diversity_score([]) == 0.0


def test_entity_importance_score_scales_with_distinct_entities():
    none = make_article(entities=[])
    two = make_article(entities=[{"text": "Nvidia", "label": "ORG"}, {"text": "Jensen Huang", "label": "PERSON"}])
    five_plus = make_article(entities=[{"text": str(i), "label": "ORG"} for i in range(7)])

    assert entity_importance_score(none) == 0.0
    assert entity_importance_score(two) == pytest.approx(2 / 5)
    assert entity_importance_score(five_plus) == 1.0


def test_entity_importance_score_deduplicates_case_insensitively():
    article = make_article(entities=[{"text": "Nvidia", "label": "ORG"}, {"text": "NVIDIA", "label": "ORG"}])
    assert entity_importance_score(article) == pytest.approx(1 / 5)
