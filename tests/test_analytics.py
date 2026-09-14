from unittest.mock import patch

import analytics


def test_lookup_country_alpha2_code():
    assert analytics._lookup_country("IN") == ("IND", "India")
    assert analytics._lookup_country("US") == ("USA", "United States")


def test_lookup_country_full_name_via_fuzzy_search():
    iso3, name = analytics._lookup_country("united states of america")
    assert iso3 == "USA"


def test_lookup_country_uses_alias_table_for_known_near_misses():
    assert analytics._lookup_country("ivory coast") == ("CIV", "Côte d'Ivoire")
    assert analytics._lookup_country("south korea")[0] == "KOR"


def test_lookup_country_returns_none_for_garbage():
    assert analytics._lookup_country("xyzgarbagenotacountry") is None


def test_normalize_country_field_splits_comma_separated_list():
    result = analytics.normalize_country_field("IN, US, xyzgarbage")
    codes = {iso3 for iso3, _ in result}
    assert codes == {"IND", "USA"}  # garbage silently dropped, not guessed


def test_normalize_country_field_empty_input():
    assert analytics.normalize_country_field("") == []
    assert analytics.normalize_country_field(None) == []


def test_country_volume_aggregates_across_normalized_variants():
    # "IN" and "india" should collapse into the same IND bucket even
    # though they're different raw DB strings.
    fake_raw = [("IN", 5), ("india", 3), ("US", 2)]
    with patch.object(analytics.db, "get_country_field_counts", return_value=fake_raw):
        result = analytics.country_volume(days=30)

    by_code = {r["iso3"]: r["count"] for r in result}
    assert by_code["IND"] == 8
    assert by_code["USA"] == 2


def test_country_volume_respects_limit():
    fake_raw = [(f"country-{i}", 1) for i in range(20)]
    with patch.object(analytics.db, "get_country_field_counts", return_value=[("IN", 1), ("US", 1), ("GB", 1)]):
        result = analytics.country_volume(limit=2)
    assert len(result) <= 2


def test_volume_summary_calls_get_article_count_three_times():
    with patch.object(analytics.db, "get_article_count", return_value=5) as mock_count:
        result = analytics.volume_summary()
    assert result == {"today": 5, "this_week": 5, "this_month": 5}
    assert mock_count.call_count == 3


def test_entity_analytics_computes_growth_and_gathers_signals():
    def fake_window_stats(entity_name, since, until):
        # first call = current window, second = prior window
        if fake_window_stats.calls == 0:
            fake_window_stats.calls += 1
            return {"count": 10, "distinct_sources": 4, "latest_published_at": "2026-09-15T00:00:00+00:00"}
        return {"count": 2, "distinct_sources": 1, "latest_published_at": "2026-09-13T00:00:00+00:00"}
    fake_window_stats.calls = 0

    with patch.object(analytics.db, "get_entity_window_stats", side_effect=fake_window_stats), \
         patch.object(analytics.db, "get_entity_sentiment", return_value={"positive": {"count": 3, "avg_score": 0.8}}), \
         patch.object(analytics.db, "get_entity_top_sources", return_value=[{"source_name": "Reuters", "count": 5}]), \
         patch.object(analytics.db, "get_entity_volume_by_day", return_value=[{"day": "2026-09-14", "count": 4}]):
        result = analytics.entity_analytics("Nvidia")

    assert result["entity_name"] == "Nvidia"
    assert result["volume_24h"] == 10
    assert result["growth_pct_24h"] == 400.0
    assert result["source_diversity_24h"] == 4
    assert result["sentiment"] == {"positive": {"count": 3, "avg_score": 0.8}}
    assert result["top_sources"] == [{"source_name": "Reuters", "count": 5}]
    assert result["daily_volume"] == [{"day": "2026-09-14", "count": 4}]
