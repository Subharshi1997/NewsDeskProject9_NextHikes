import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

logger = logging.getLogger("news_research_tool.pipeline.validation")

MIN_TITLE_LENGTH = 5
MAX_FUTURE_SKEW = timedelta(hours=48)  # tolerance for clock skew across providers/timezones


def is_valid_url(url):
    if not url:
        return False
    parts = urlsplit(url)
    return bool(parts.scheme in ("http", "https") and parts.netloc)


def validate_article(article):
    """Returns (is_valid, reasons). Each rule and why it exists:

    - title missing/too short: title drives dedup, clustering, and display
      -- an article that can't be titled can't be deduplicated or shown
      sensibly.
    - url invalid: articles here are metadata + a link back to the source
      (Rule 10, no full-article storage) -- a broken link makes the article
      useless regardless of how good the rest of the data is.
    - source missing: breaks the sources table's FK and source-quality
      scoring. Current providers always backfill "Unknown" rather than
      leaving this empty, so in practice this is a defensive backstop, not
      something real traffic hits today.

    Publication date is handled separately (see clean_published_at) -- an
    impossible date is cleared, not grounds for rejecting the whole
    article, since the title/url/description can still be legitimate.

    "Clearly duplicate" (also in section 20's list) isn't checked here --
    that's pipeline.dedup's job, run after validation so garbage doesn't
    get compared against.
    """
    reasons = []
    if not article.title or len(article.title.strip()) < MIN_TITLE_LENGTH:
        reasons.append("title missing or too short")
    if not is_valid_url(article.url):
        reasons.append("url missing or invalid")
    if not article.source_name or not article.source_name.strip():
        reasons.append("source missing")
    return (len(reasons) == 0, reasons)


def clean_published_at(article, now=None):
    """Clears (doesn't reject) a publication date that's impossible --
    e.g. clearly in the future. A cleared date falls back to
    scoring.recency_score()'s existing 0.0-for-missing-date behavior.
    """
    if not article.published_at:
        return
    try:
        published = datetime.fromisoformat(article.published_at)
    except ValueError:
        article.published_at = None
        return
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    if published > now + MAX_FUTURE_SKEW:
        logger.warning(
            "validation: clearing impossible future published_at=%r for %r",
            article.published_at, article.title,
        )
        article.published_at = None


def validate_articles(articles, now=None):
    """Cleans publication dates and drops articles that fail validate_article,
    logging why. Returns the surviving list."""
    valid = []
    rejected = 0
    for article in articles:
        clean_published_at(article, now=now)
        ok, reasons = validate_article(article)
        if ok:
            valid.append(article)
        else:
            rejected += 1
            logger.info("validation: rejected article %r: %s", article.title, ", ".join(reasons))
    if rejected:
        logger.info("validation: rejected %d/%d articles", rejected, len(articles))
    return valid
