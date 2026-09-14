import logging
from datetime import datetime, timedelta, timezone

import pycountry

import db

logger = logging.getLogger("news_research_tool.analytics")

# Small supplementary table for common near-misses pycountry's fuzzy search
# doesn't resolve (different aliasing conventions, not typos). Deliberately
# not exhaustive -- genuine upstream data typos (e.g. a real RSS/API field
# observed containing "burkina fasco") are left unresolved rather than
# guessed at. See docs/ANALYTICS.md for the full known-gaps list.
COUNTRY_ALIASES = {
    "ivory coast": "CIV",
    "cote d'ivoire": "CIV",
    "dr congo": "COD",
    "democratic republic of congo": "COD",
    "republic of congo": "COG",
    "macau": "MAC",
    "south korea": "KOR",
    "north korea": "PRK",
    "russia": "RUS",
    "iran": "IRN",
    "syria": "SYR",
    "laos": "LAO",
    "vietnam": "VNM",
    "bolivia": "BOL",
    "venezuela": "VEN",
    "tanzania": "TZA",
    "uk": "GBR",
    "usa": "USA",
    "uae": "ARE",
}


def _lookup_country(piece):
    """Returns (iso3_code, display_name) or None. Tries alpha-2/alpha-3
    code lookup first (exact), then the alias table, then pycountry's
    fuzzy name search (handles most lowercase full names like "india" or
    "united states of america").
    """
    piece = piece.strip()
    if not piece:
        return None

    if len(piece) == 2:
        match = pycountry.countries.get(alpha_2=piece.upper())
        if match:
            return match.alpha_3, match.name
    if len(piece) == 3:
        match = pycountry.countries.get(alpha_3=piece.upper())
        if match:
            return match.alpha_3, match.name

    alias = COUNTRY_ALIASES.get(piece.lower())
    if alias:
        match = pycountry.countries.get(alpha_3=alias)
        if match:
            return match.alpha_3, match.name

    try:
        results = pycountry.countries.search_fuzzy(piece)
        if results:
            return results[0].alpha_3, results[0].name
    except LookupError:
        pass
    return None


def normalize_country_field(raw):
    """DB country values are messy: 2-letter codes (IN, US), lowercase
    full names (india), or comma-separated lists of many countries (some
    NewsData.io articles tag dozens of countries on one article). Splits
    and normalizes each piece to (iso3_code, display_name). Unrecognized
    pieces are silently dropped, not guessed at -- partial coverage is
    expected and documented, not a bug.
    """
    if not raw:
        return []
    resolved = []
    for piece in raw.split(","):
        result = _lookup_country(piece)
        if result:
            resolved.append(result)
    return resolved


def volume_summary():
    """Articles Today / This Week / This Month counts (roadmap #14)."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week_start = (now - timedelta(days=7)).isoformat()
    month_start = (now - timedelta(days=30)).isoformat()
    return {
        "today": db.get_article_count(since=today_start),
        "this_week": db.get_article_count(since=week_start),
        "this_month": db.get_article_count(since=month_start),
    }


def country_volume(days=30, limit=15):
    """Aggregates raw (messy) country field values into clean ISO-3-coded
    country counts, splitting multi-country fields along the way. Returns
    a list of {iso3, name, count}, sorted by count descending.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    raw_counts = db.get_country_field_counts(since=since)

    totals = {}
    for raw_value, article_count in raw_counts:
        for iso3, name in normalize_country_field(raw_value):
            entry = totals.setdefault(iso3, {"iso3": iso3, "name": name, "count": 0})
            entry["count"] += article_count

    ranked = sorted(totals.values(), key=lambda r: r["count"], reverse=True)
    return ranked[:limit]


def entity_analytics(entity_name, days=30):
    """Roadmap #17 "Topic Analytics", operating over extracted entities
    per the same design choice as pipeline.trending (see docs/NLP.md):
    volume, 24h growth, sentiment breakdown, top sources, historical daily
    trend for one entity.
    """
    now = datetime.now(timezone.utc)
    current_start = now - timedelta(hours=24)
    prior_start = current_start - timedelta(hours=24)

    current = db.get_entity_window_stats(entity_name, since=current_start.isoformat(), until=now.isoformat())
    prior = db.get_entity_window_stats(entity_name, since=prior_start.isoformat(), until=current_start.isoformat())
    growth_pct = round((current["count"] - prior["count"]) / max(prior["count"], 1) * 100, 1)

    return {
        "entity_name": entity_name,
        "volume_24h": current["count"],
        "growth_pct_24h": growth_pct,
        "source_diversity_24h": current["distinct_sources"],
        "sentiment": db.get_entity_sentiment(entity_name),
        "top_sources": db.get_entity_top_sources(entity_name),
        "daily_volume": db.get_entity_volume_by_day(entity_name, days=days),
    }
