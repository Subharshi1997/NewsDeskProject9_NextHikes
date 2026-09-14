import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("news_research_tool.pipeline.scoring")

DEFAULT_SOURCES_FILE = Path(__file__).resolve().parent.parent / "config" / "sources.json"

# article_score (this project's "quality_score" == the roadmap's
# "Importance Score" -- same architectural slot, kept as one field rather
# than two parallel scores) =
#   source*w1 + recency*w2 + completeness*w3 + originality*w4
#   + source_diversity*w5 + entity_importance*w6
# Defaults, not fixed constants — documented in docs/DATA_PIPELINE.md.
# Source quality is weighted heaviest since a reputable outlet's editorial
# process is the strongest available signal on this app's scale (no
# reader-engagement data exists to inform "relevance").
DEFAULT_WEIGHTS = {
    "source": 0.30,
    "recency": 0.25,
    "completeness": 0.15,
    "originality": 0.10,
    "source_diversity": 0.15,
    "entity_importance": 0.05,
}

RECENCY_HALF_LIFE_HOURS = 12  # recency score halves every N hours of age
MAX_DIVERSITY_SOURCES = 5  # 5+ distinct sources covering a story = max diversity signal
MAX_ENTITY_COUNT = 5  # 5+ distinct entities mentioned = max entity-importance signal


class SourceScorer:
    """Looks up a configurable quality score (1-5) for a source_name from
    config/sources.json. Falls back to the config's default_quality_score
    for anything not explicitly listed.
    """

    def __init__(self, sources_file=None):
        self.sources_file = Path(sources_file) if sources_file else DEFAULT_SOURCES_FILE
        self._config = self._load()

    def _load(self):
        if not self.sources_file.exists():
            return {"default_quality_score": 2, "sources": []}
        with self.sources_file.open("r", encoding="utf-8") as f:
            return json.load(f)

    def score(self, source_name):
        default = self._config.get("default_quality_score", 2)
        if not source_name:
            return default
        target = source_name.strip().lower()
        for entry in self._config.get("sources", []):
            if entry["source_name"].strip().lower() == target:
                return entry["quality_score"]
        for entry in self._config.get("sources", []):
            known = entry["source_name"].strip().lower()
            if known in target or target in known:
                return entry["quality_score"]
        return default


def recency_score(published_at, now=None):
    """1.0 for a brand-new article, exponential decay with a
    RECENCY_HALF_LIFE_HOURS half-life. 0.0 if published_at is missing/unparseable.
    """
    if not published_at:
        return 0.0
    try:
        published = datetime.fromisoformat(published_at)
    except ValueError:
        return 0.0
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    age_hours = max((now - published).total_seconds() / 3600, 0)
    return 0.5 ** (age_hours / RECENCY_HALF_LIFE_HOURS)


def completeness_score(article):
    """Fraction of the normalized schema's richer fields that are populated."""
    fields = [article.title, article.description, article.content, article.image_url, article.author]
    return sum(1 for f in fields if f) / len(fields)


def originality_score(article, story_articles):
    """1.0 if this article was the earliest-published in its story cluster
    (broke the story first), decaying for later arrivals. 0.5 when
    published_at is missing for enough of the cluster to rank confidently.
    """
    if not story_articles or len(story_articles) == 1:
        return 1.0
    dated = [a for a in story_articles if a.published_at]
    if not dated:
        return 0.5
    sorted_by_time = sorted(dated, key=lambda a: a.published_at)
    rank = next((i for i, a in enumerate(sorted_by_time) if a is article), None)
    if rank is None:
        return 0.5
    return max(1.0 - (rank / len(sorted_by_time)), 0.1)


def source_diversity_score(story_articles):
    """How many distinct publications (not providers) cover this story --
    a proxy for how significant/corroborated it is, not just how many
    copies of the same wire report exist (those were already collapsed by
    pipeline.dedup before clustering). Normalized to [0, 1], capped at
    MAX_DIVERSITY_SOURCES.
    """
    if not story_articles:
        return 0.0
    distinct_sources = {a.source_name for a in story_articles if a.source_name}
    return min(len(distinct_sources) / MAX_DIVERSITY_SOURCES, 1.0)


def entity_importance_score(article):
    """Crude proxy for substance/newsworthiness: how many distinct named
    entities this article mentions, normalized to [0, 1]. This is NOT a
    true corpus-wide entity-prominence signal (that would need looking up
    each entity's overall entities.mention_count) -- a deliberate v1
    simplification, documented in docs/NLP.md, that keeps this module free
    of a DB dependency.
    """
    if not article.entities:
        return 0.0
    distinct = {e["text"].lower() for e in article.entities}
    return min(len(distinct) / MAX_ENTITY_COUNT, 1.0)


def score_article(article, story_articles=None, weights=None, source_scorer=None, now=None):
    weights = weights or DEFAULT_WEIGHTS
    source_scorer = source_scorer or SourceScorer()
    story_articles = story_articles or [article]

    source = min(max(source_scorer.score(article.source_name), 0), 5) / 5
    recency = recency_score(article.published_at, now=now)
    completeness = completeness_score(article)
    originality = originality_score(article, story_articles)
    diversity = source_diversity_score(story_articles)
    entity_importance = entity_importance_score(article)

    total = (
        source * weights.get("source", 0)
        + recency * weights.get("recency", 0)
        + completeness * weights.get("completeness", 0)
        + originality * weights.get("originality", 0)
        + diversity * weights.get("source_diversity", 0)
        + entity_importance * weights.get("entity_importance", 0)
    )
    article.quality_score = round(total, 4)
    return article.quality_score


def select_primary(story_articles, weights=None, source_scorer=None, now=None):
    """Section 11: choose the best version of a story. Scores every
    article in the cluster, marks the highest-scoring one is_primary=True,
    the rest False. The frontend should render the primary article, not
    whichever provider happened to return first.
    """
    source_scorer = source_scorer or SourceScorer()
    for article in story_articles:
        score_article(article, story_articles=story_articles, weights=weights, source_scorer=source_scorer, now=now)
        article.is_primary = False

    best = max(story_articles, key=lambda a: a.quality_score or 0)
    best.is_primary = True
    logger.debug("scoring: story primary = %r (score=%.3f)", best.title, best.quality_score)
    return best
