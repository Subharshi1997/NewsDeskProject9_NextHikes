import logging
import os
from datetime import datetime, timezone

import requests

from .base import NewsProvider, NormalizedArticle

logger = logging.getLogger("news_research_tool.providers.newsdata")

NEWSDATA_URL = "https://newsdata.io/api/1/latest"


class NewsDataProvider(NewsProvider):
    name = "newsdata"

    def __init__(self, api_key=None, timeout=10):
        self.api_key = api_key or os.getenv("NEWSDATA_API_KEY")
        self.timeout = timeout

    @property
    def enabled(self):
        return bool(self.api_key)

    def fetch_news(self, query=None, category=None, country=None, language="en", page=None, page_size=10):
        if not self.api_key:
            raise RuntimeError("NewsDataProvider: NEWSDATA_API_KEY is not set")

        params = {"apikey": self.api_key, "language": language or "en", "size": page_size}
        if query:
            params["q"] = query
        if category:
            params["category"] = category
        if country:
            params["country"] = country
        if page:
            params["page"] = page

        response = requests.get(NEWSDATA_URL, params=params, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if data.get("status") != "success":
            raise RuntimeError(f"NewsData.io request failed: {data}")

        articles = [self._normalize(a) for a in (data.get("results") or [])]
        logger.info("newsdata: fetched %d articles for query=%r", len(articles), query)
        return articles

    def _normalize(self, a):
        return NormalizedArticle(
            article_id=a.get("article_id") or a.get("link", ""),
            title=a.get("title") or "",
            url=a.get("link", ""),
            provider=self.name,
            source_name=a.get("source_id") or a.get("source_name") or "Unknown",
            description=a.get("description"),
            content=self._clean_content(a.get("content")),
            image_url=a.get("image_url"),
            source_url=a.get("source_url"),
            author=self._join(a.get("creator")),
            published_at=self._parse_date(a.get("pubDate")),
            fetched_at=datetime.now(timezone.utc).isoformat(),
            language=a.get("language"),
            country=self._join(a.get("country")),
            category=self._join(a.get("category")),
            keywords=a.get("keywords") or [],
        )

    @staticmethod
    def _clean_content(content):
        if content in (None, "ONLY AVAILABLE IN PAID PLANS"):
            return None
        return content

    @staticmethod
    def _join(value):
        if isinstance(value, list):
            return ", ".join(value) if value else None
        return value

    @staticmethod
    def _parse_date(value):
        if not value:
            return None
        try:
            return (
                datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                .replace(tzinfo=timezone.utc)
                .isoformat()
            )
        except ValueError:
            return value
