import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import feedparser

from .base import NewsProvider, NormalizedArticle

logger = logging.getLogger("news_research_tool.providers.rss")

DEFAULT_SOURCES_FILE = Path(__file__).resolve().parent.parent / "config" / "rss_sources.json"


class RSSProvider(NewsProvider):
    """Generic RSS ingestion. Sources come from a config file, never
    hardcoded — see config/rss_sources.json.

    RSS feeds aren't keyword-searchable like a REST API: each feed only
    exposes its latest items. When a query is given, we pull the latest
    items from every configured feed and filter client-side by whether the
    query text appears in the title/summary.
    """

    name = "rss"

    def __init__(self, sources_file=None, timeout=10):
        self.sources_file = Path(sources_file) if sources_file else DEFAULT_SOURCES_FILE
        self.timeout = timeout

    @property
    def enabled(self):
        return self.sources_file.exists()

    def load_sources(self):
        if not self.sources_file.exists():
            return []
        with self.sources_file.open("r", encoding="utf-8") as f:
            return json.load(f)

    def fetch_news(self, query=None, category=None, country=None, language=None, page=None, page_size=10):
        sources = self.load_sources()
        if category:
            sources = [s for s in sources if s.get("category") == category]
        if country:
            sources = [s for s in sources if s.get("country") == country]
        if language:
            sources = [s for s in sources if s.get("language") == language]

        query_lower = query.lower().strip() if query else None
        results = []
        for source in sources:
            try:
                results.extend(self._fetch_source(source, query_lower, page_size))
            except Exception:
                # One bad feed must not take down the whole provider.
                logger.warning("rss: failed to fetch source %r", source.get("name"), exc_info=True)
                continue

        logger.info("rss: fetched %d articles across %d sources for query=%r", len(results), len(sources), query)
        return results

    def _fetch_source(self, source, query_lower, page_size):
        parsed = feedparser.parse(source["url"])
        articles = []
        for entry in parsed.entries[:page_size]:
            article = self._normalize(entry, source)
            if query_lower and not self._matches(article, query_lower):
                continue
            articles.append(article)
        return articles

    @staticmethod
    def _matches(article, query_lower):
        haystack = f"{article.title or ''} {article.description or ''}".lower()
        return query_lower in haystack

    def _normalize(self, entry, source):
        return NormalizedArticle(
            article_id=entry.get("id") or entry.get("link", ""),
            title=entry.get("title") or "",
            url=entry.get("link", ""),
            provider=self.name,
            source_name=source.get("name", "Unknown"),
            description=entry.get("summary"),
            content=None,
            image_url=self._extract_image(entry),
            source_url=source.get("url"),
            author=entry.get("author"),
            published_at=self._parse_date(entry),
            fetched_at=datetime.now(timezone.utc).isoformat(),
            language=source.get("language"),
            country=source.get("country"),
            category=source.get("category"),
            keywords=[tag.get("term") for tag in entry.get("tags", []) if tag.get("term")],
        )

    @staticmethod
    def _extract_image(entry):
        media = entry.get("media_content") or entry.get("media_thumbnail")
        if isinstance(media, list) and media:
            return media[0].get("url")
        return None

    @staticmethod
    def _parse_date(entry):
        parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
        if not parsed_time:
            return None
        return datetime(*parsed_time[:6], tzinfo=timezone.utc).isoformat()
