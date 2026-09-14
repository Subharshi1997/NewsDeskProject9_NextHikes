import logging
from datetime import datetime, timedelta, timezone

import db

logger = logging.getLogger("news_research_tool.pipeline.trending")

WINDOWS = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}

# Trending here operates over extracted entities (people/orgs/places/etc,
# from pipeline.entities), not full topic modeling -- a deliberate v1
# simplification (see docs/NLP.md). This means a conceptual/thematic
# phrase like "AI Regulation" won't surface as its own trending item
# unless it also happens to be tagged as an entity; a named entity like
# "Nvidia" or "RBI" will. Extending this to category-level trending too is
# a natural follow-up (db.get_articles already supports category
# filtering) but isn't done here to keep this module's scope contained.
DEFAULT_WEIGHTS = {
    "growth": 0.4,
    "volume": 0.2,
    "recency": 0.2,
    "diversity": 0.2,
}

RECENCY_HALF_LIFE_HOURS = 6  # trending should reward very recent activity more sharply than article-level scoring
MAX_VOLUME_FOR_SCORE = 20  # 20+ articles in-window = max volume signal
MAX_GROWTH_RATIO_FOR_SCORE = 3.0  # cap extreme/noisy growth ratios (e.g. 0 -> 1 article) at 300%
MAX_DIVERSITY_SOURCES = 5


def compute_trending(window="24h", top_n=10, min_volume=2, weights=None, now=None):
    """Ranks entities by a transparent trending-momentum score -- NOT just
    raw article-volume ranking. Combines:
      - growth: this window's volume vs. the prior equal-length window
      - volume: absolute article count in-window (capped)
      - recency: how fresh the most recent mention is
      - diversity: how many distinct sources are covering it

    Returns a list of dicts sorted by trending_score, richest first, each
    carrying the raw numbers so the UI can show *why* something is
    trending (roadmap section 34), not just the final score.
    """
    weights = weights or DEFAULT_WEIGHTS
    now = now or datetime.now(timezone.utc)
    window_delta = WINDOWS.get(window, WINDOWS["24h"])
    current_start = now - window_delta
    prior_start = current_start - window_delta

    candidates = db.get_entity_activity(since=prior_start.isoformat())
    results = []
    for entity_name, entity_type in candidates:
        current = db.get_entity_window_stats(entity_name, since=current_start.isoformat(), until=now.isoformat())
        if current["count"] < min_volume:
            continue
        prior = db.get_entity_window_stats(entity_name, since=prior_start.isoformat(), until=current_start.isoformat())

        volume = current["count"]
        prior_volume = prior["count"]
        growth_ratio = (volume - prior_volume) / max(prior_volume, 1)
        diversity = min(current["distinct_sources"] / MAX_DIVERSITY_SOURCES, 1.0)
        recency = _recency_fraction(current["latest_published_at"], now)

        score = (
            min(max(growth_ratio, 0), MAX_GROWTH_RATIO_FOR_SCORE) / MAX_GROWTH_RATIO_FOR_SCORE * weights["growth"]
            + min(volume / MAX_VOLUME_FOR_SCORE, 1.0) * weights["volume"]
            + recency * weights["recency"]
            + diversity * weights["diversity"]
        )

        results.append({
            "entity_name": entity_name,
            "entity_type": entity_type,
            "window": window,
            "volume": volume,
            "prior_volume": prior_volume,
            "growth_pct": round(growth_ratio * 100, 1),
            "source_diversity": current["distinct_sources"],
            "trending_score": round(score, 4),
        })

    results.sort(key=lambda r: r["trending_score"], reverse=True)
    logger.info("trending: ranked %d candidates for window=%s, returning top %d", len(results), window, top_n)
    return results[:top_n]


def _recency_fraction(latest_iso, now):
    if not latest_iso:
        return 0.0
    try:
        latest = datetime.fromisoformat(latest_iso)
    except ValueError:
        return 0.0
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    age_hours = max((now - latest).total_seconds() / 3600, 0)
    return 0.5 ** (age_hours / RECENCY_HALF_LIFE_HOURS)
