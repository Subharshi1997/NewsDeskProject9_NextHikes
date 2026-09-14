import logging
import os
import re
from datetime import datetime, timezone

import requests

from .base import NewsProvider, NormalizedArticle

logger = logging.getLogger("news_research_tool.providers.gnews")

SEARCH_URL = "https://gnews.io/api/v4/search"
TOP_HEADLINES_URL = "https://gnews.io/api/v4/top-headlines"

CONTENT_TRUNCATION_RE = re.compile(r"\s*\[\d+ chars\]$")


class GNewsProvider(NewsProvider):
    """gnews.io. Free-tier notes (see docs/NEWS_PROVIDERS.md): ~100
    requests/day, and "real-time" results are delayed ~12 hours on the free
    plan (per the API's own response payload).
    """

    name = "gnews"

    def __init__(self, api_key=None, timeout=10):
        self.api_key = api_key or os.getenv("GNEWS_API_KEY")
        self.timeout = timeout

    @property
    def enabled(self):
        return bool(self.api_key)

    def fetch_news(self, query=None, category=None, country=None, language="en", page=None, page_size=10):
        if not self.api_key:
            raise RuntimeError("GNewsProvider: GNEWS_API_KEY is not set")

        url = SEARCH_URL if query else TOP_HEADLINES_URL
        params = {"apikey": self.api_key, "lang": language or "en", "max": page_size}
        if query:
            params["q"] = query
        if category:
            params["category"] = category
        if country:
            params["country"] = country

        response = requests.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if "errors" in data:
            raise RuntimeError(f"GNews request failed: {data['errors']}")

        articles = [self._normalize(a, category=category) for a in data.get("articles", [])]
        logger.info("gnews: fetched %d articles for query=%r", len(articles), query)
        return articles

    def _normalize(self, a, category=None):
        source = a.get("source") or {}
        return NormalizedArticle(
            article_id=a.get("id") or a.get("url", ""),
            title=a.get("title") or "",
            url=a.get("url", ""),
            provider=self.name,
            source_name=source.get("name") or "Unknown",
            description=a.get("description"),
            content=self._clean_content(a.get("content")),
            image_url=a.get("image"),
            source_url=source.get("url"),
            published_at=self._parse_date(a.get("publishedAt")),
            fetched_at=datetime.now(timezone.utc).isoformat(),
            language=a.get("lang"),
            country=source.get("country"),
            category=category,
            keywords=[],
        )

    @staticmethod
    def _clean_content(content):
        if not content:
            return None
        return CONTENT_TRUNCATION_RE.sub("", content).strip() or None

    @staticmethod
    def _parse_date(value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
        except ValueError:
            return value
