import logging
import os
import re
from datetime import datetime, timezone

import requests

from .base import NewsProvider, NormalizedArticle

logger = logging.getLogger("news_research_tool.providers.newsapi")

EVERYTHING_URL = "https://newsapi.org/v2/everything"
TOP_HEADLINES_URL = "https://newsapi.org/v2/top-headlines"

CONTENT_TRUNCATION_RE = re.compile(r"\s*\[\+\d+ chars\]$")


class NewsAPIProvider(NewsProvider):
    """newsapi.org. Free-tier notes (see docs/NEWS_PROVIDERS.md): dev-only
    license (blocks non-localhost production use), and /everything only
    covers roughly the last month of articles.
    """

    name = "newsapi"

    def __init__(self, api_key=None, timeout=10):
        self.api_key = api_key or os.getenv("NEWS_API_KEY")
        self.timeout = timeout

    @property
    def enabled(self):
        return bool(self.api_key)

    def fetch_news(self, query=None, category=None, country=None, language="en", page=None, page_size=10):
        if not self.api_key:
            raise RuntimeError("NewsAPIProvider: NEWS_API_KEY is not set")

        if query:
            url = EVERYTHING_URL
            params = {"apiKey": self.api_key, "q": query, "language": language or "en", "pageSize": page_size}
        else:
            # /top-headlines 400s unless at least one of q/sources/category/
            # country is present -- default to "us" so a general sweep
            # (no query, no filters) doesn't fail outright.
            url = TOP_HEADLINES_URL
            params = {"apiKey": self.api_key, "pageSize": page_size}
            if category:
                params["category"] = category
            if country:
                params["country"] = country
            if not category and not country:
                params["country"] = "us"
        if page:
            params["page"] = page

        response = requests.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if data.get("status") != "ok":
            raise RuntimeError(f"NewsAPI request failed: {data}")

        articles = [
            self._normalize(a, language=language, category=category, country=country)
            for a in data.get("articles", [])
        ]
        logger.info("newsapi: fetched %d articles for query=%r", len(articles), query)
        return articles

    def _normalize(self, a, language=None, category=None, country=None):
        source = a.get("source") or {}
        return NormalizedArticle(
            article_id=a.get("url", ""),
            title=a.get("title") or "",
            url=a.get("url", ""),
            provider=self.name,
            source_name=source.get("name") or "Unknown",
            description=a.get("description"),
            content=self._clean_content(a.get("content")),
            image_url=a.get("urlToImage"),
            author=a.get("author"),
            published_at=self._parse_date(a.get("publishedAt")),
            fetched_at=datetime.now(timezone.utc).isoformat(),
            # NewsAPI doesn't echo language/category/country back per
            # article -- backfilled from what was actually requested,
            # since the response set was already filtered by them.
            language=language,
            country=country,
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
