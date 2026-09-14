import logging

import db
from pipeline.clustering import cluster_stories
from pipeline.dedup import deduplicate
from pipeline.entities import extract_article_entities
from pipeline.scoring import SourceScorer, select_primary
from pipeline.sentiment import analyze_article_sentiment
from pipeline.validation import validate_articles
from providers.registry import get_registry

logger = logging.getLogger("news_research_tool.pipeline.ingest")

# Only stories corroborated by 2+ articles get an AI summary generated --
# keeps LLM calls per cycle proportional to "stories worth summarizing",
# not to raw article count (most stories in a batch are single-article).
MIN_ARTICLES_FOR_SUMMARY = 2

# Timeline/coverage-comparison/why-this-matters ("major story" treatment,
# roadmap sections 27/28/30) use a stricter bar than the basic summary --
# these are richer, more expensive-to-generate content meant for genuinely
# well-corroborated stories, not every 2-source story.
MIN_ARTICLES_FOR_EXTRAS = 3


def run_ingest_cycle(queries=None, category=None, country=None, language="en", page_size=10):
    """One full pass: fetch from every enabled provider -> normalize
    (already done inside providers) -> validate -> dedup -> enrich
    (sentiment + entities) -> cluster -> score -> summarize -> store.

    queries=None fetches each provider's general/top feed once. A list of
    queries runs the whole pipeline once per query and merges the results
    before deduping, so the same story surfaced by two different queries
    still collapses into one.
    """
    registry = get_registry()
    queries = queries or [None]

    all_articles = []
    for query in queries:
        all_articles.extend(
            registry.fetch_all(query=query, category=category, country=country, language=language, page_size=page_size)
        )
    logger.info("ingest: fetched %d raw articles across %d quer%s", len(all_articles), len(queries), "y" if len(queries) == 1 else "ies")

    all_articles = validate_articles(all_articles)
    deduplicate(all_articles)

    _enrich_with_nlp(all_articles)

    story_map = cluster_stories(all_articles)

    source_scorer = SourceScorer()
    for story_articles in story_map.values():
        select_primary(story_articles, source_scorer=source_scorer)

    story_summaries = _generate_story_summaries(story_map)
    story_extras = _generate_story_extras(story_map)

    inserted, skipped = db.store_articles(
        all_articles, source_scorer=source_scorer,
        story_summaries=story_summaries, story_extras=story_extras,
    )

    return {
        "fetched": len(all_articles),
        "stories": len(story_map),
        "inserted": inserted,
        "skipped": skipped,
        "summarized": len(story_summaries),
        "analyzed": len(story_extras),
        "provider_status": registry.status_report(),
    }


def _enrich_with_nlp(articles):
    """Sentiment + entity extraction, skipped for anything already flagged
    a duplicate -- no point spending model time on data that won't be
    stored. Failures in the underlying models are already handled
    gracefully inside pipeline.sentiment/pipeline.entities (they return
    None/[] rather than raising), so this loop can't fail an ingest cycle.
    """
    for article in articles:
        if article.is_duplicate:
            continue
        article.sentiment, article.sentiment_score = analyze_article_sentiment(article)
        article.entities = extract_article_entities(article)


def _generate_story_summaries(story_map):
    """Generates a fresh AI summary only for multi-article stories that
    don't already have a cached one in the DB. Returns {story_id: text}
    for the stories that just got a new summary this cycle -- db.store_articles
    only writes stories present in this dict, so an existing cached summary
    is never regenerated or clobbered.
    """
    from langchain_config import generate_story_summary  # deferred: avoids
    # pipeline.ingest requiring GROQ_API_KEY to import when summaries
    # aren't needed (e.g. most tests import this module without a key set).

    summaries = {}
    for story_id, story_articles in story_map.items():
        if len(story_articles) < MIN_ARTICLES_FOR_SUMMARY:
            continue
        existing = db.get_story(story_id)
        if existing and existing.get("summary"):
            continue
        try:
            summaries[story_id] = generate_story_summary(story_articles)
        except Exception:
            logger.warning("ingest: story summary generation failed for %r", story_id, exc_info=True)
    if summaries:
        logger.info("ingest: generated %d new story summaries", len(summaries))
    return summaries


def _generate_story_extras(story_map):
    """Generates timeline/coverage-comparison/why-this-matters only for
    "major" stories (MIN_ARTICLES_FOR_EXTRAS+) that don't already have
    these cached. Returns {story_id: {"timeline":..., "coverage_comparison":...,
    "why_matters":...}} for stories analyzed this cycle -- same
    never-regenerate-once-cached pattern as _generate_story_summaries.
    """
    from langchain_config import generate_story_extras  # deferred, same
    # reason as _generate_story_summaries's deferred import.

    extras = {}
    for story_id, story_articles in story_map.items():
        if len(story_articles) < MIN_ARTICLES_FOR_EXTRAS:
            continue
        existing = db.get_story(story_id)
        if existing and existing.get("why_matters"):
            continue
        try:
            extras[story_id] = generate_story_extras(story_articles)
        except Exception:
            logger.warning("ingest: story extras generation failed for %r", story_id, exc_info=True)
    if extras:
        logger.info("ingest: generated extras (timeline/comparison/why-matters) for %d stories", len(extras))
    return extras
