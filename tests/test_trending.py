from datetime import datetime, timezone
from unittest.mock import patch

import pipeline.trending as trending


def test_compute_trending_ranks_growing_entity_first():
    now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)

    # Call order per entity is (current-window stats, prior-window stats);
    # entities are processed in the order get_entity_activity returns them.
    stats_sequence = [
        {"count": 10, "distinct_sources": 5, "latest_published_at": "2026-09-15T11:30:00+00:00"},  # Nvidia current
        {"count": 2, "distinct_sources": 1, "latest_published_at": "2026-09-13T10:00:00+00:00"},   # Nvidia prior
        {"count": 2, "distinct_sources": 1, "latest_published_at": "2026-09-15T00:00:00+00:00"},   # Obscure Co current
        {"count": 2, "distinct_sources": 1, "latest_published_at": "2026-09-13T00:00:00+00:00"},   # Obscure Co prior
    ]

    with patch.object(trending.db, "get_entity_activity", return_value=[("Nvidia", "ORG"), ("Obscure Co", "ORG")]), \
         patch.object(trending.db, "get_entity_window_stats", side_effect=stats_sequence):
        results = trending.compute_trending(window="24h", now=now)

    assert results[0]["entity_name"] == "Nvidia"
    assert results[0]["growth_pct"] > 0
    assert results[0]["volume"] == 10
    assert results[0]["source_diversity"] == 5


def test_compute_trending_filters_below_min_volume():
    with patch.object(trending.db, "get_entity_activity", return_value=[("Rare", "ORG")]), \
         patch.object(trending.db, "get_entity_window_stats", return_value={"count": 1, "distinct_sources": 1, "latest_published_at": None}):
        results = trending.compute_trending(min_volume=2)
    assert results == []


def test_compute_trending_respects_top_n():
    with patch.object(trending.db, "get_entity_activity", return_value=[("A", "ORG"), ("B", "ORG"), ("C", "ORG")]), \
         patch.object(trending.db, "get_entity_window_stats", return_value={"count": 5, "distinct_sources": 2, "latest_published_at": "2026-09-15T00:00:00+00:00"}):
        results = trending.compute_trending(top_n=2)
    assert len(results) == 2


def test_recency_fraction_is_one_for_now_and_zero_for_missing():
    now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
    assert trending._recency_fraction(None, now) == 0.0
    assert trending._recency_fraction(now.isoformat(), now) == 1.0


def test_recency_fraction_decays_with_age():
    now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
    six_hours_old = (now.replace(hour=6)).isoformat()
    fraction = trending._recency_fraction(six_hours_old, now)
    assert 0.4 < fraction < 0.6
