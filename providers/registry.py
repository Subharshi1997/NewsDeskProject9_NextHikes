import logging
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

from .gnews_provider import GNewsProvider
from .newsapi_provider import NewsAPIProvider
from .newsdata_provider import NewsDataProvider
from .rss_provider import RSSProvider

logger = logging.getLogger("news_research_tool.providers.registry")


@dataclass
class ProviderStatus:
    name: str
    status: str = "unknown"  # "ok" | "error" | "disabled"
    last_success: Optional[str] = None
    last_failure: Optional[str] = None
    last_error: Optional[str] = None
    articles_fetched: int = 0
    response_time_ms: Optional[float] = None
    rate_limited: bool = False


class ProviderRegistry:
    """Owns every configured NewsProvider and fans a request out to all of
    them. A failure in one provider is caught, logged, and skipped — it
    never stops the others from being tried (see fetch_all).
    """

    def __init__(self, providers=None):
        self.providers = providers if providers is not None else self._default_providers()
        self.status = {p.name: ProviderStatus(name=p.name) for p in self.providers}

    @staticmethod
    def _default_providers():
        candidates = [NewsDataProvider(), RSSProvider(), NewsAPIProvider(), GNewsProvider()]
        enabled_flags = {
            "newsdata": os.getenv("NEWS_PROVIDER_NEWS_DATA_ENABLED", "true").lower() != "false",
            "rss": os.getenv("NEWS_PROVIDER_RSS_ENABLED", "true").lower() != "false",
            "newsapi": os.getenv("NEWS_PROVIDER_NEWS_API_ENABLED", "true").lower() != "false",
            "gnews": os.getenv("NEWS_PROVIDER_GNEWS_ENABLED", "true").lower() != "false",
        }
        return [p for p in candidates if enabled_flags.get(p.name, True)]

    def active_providers(self):
        return [p for p in self.providers if p.enabled]

    def fetch_all(self, query=None, category=None, country=None, language=None, page=None,
                  page_size=10, max_retries=2, backoff_base=0.5):
        """Query every enabled provider and return the combined article list.
        A provider that errors out after retries is skipped, not fatal.
        """
        all_articles = []
        for provider in self.providers:
            status = self.status[provider.name]
            if not provider.enabled:
                status.status = "disabled"
                continue

            articles, error = self._fetch_with_retry(
                provider, query, category, country, language, page, page_size,
                max_retries, backoff_base,
            )
            if error is not None:
                status.status = "error"
                status.last_failure = datetime.now(timezone.utc).isoformat()
                status.last_error = str(error)
                logger.error("provider %s failed after retries: %s", provider.name, error)
                continue

            status.status = "ok"
            status.last_success = datetime.now(timezone.utc).isoformat()
            status.articles_fetched = len(articles)
            all_articles.extend(articles)

        return all_articles

    def _fetch_with_retry(self, provider, query, category, country, language, page, page_size,
                           max_retries, backoff_base):
        last_error = None
        for attempt in range(max_retries + 1):
            start = time.monotonic()
            try:
                articles = provider.fetch_news(
                    query=query, category=category, country=country,
                    language=language, page=page, page_size=page_size,
                )
                self.status[provider.name].response_time_ms = (time.monotonic() - start) * 1000
                return articles, None
            except Exception as e:
                last_error = e
                if "429" in str(e) or "rate limit" in str(e).lower():
                    self.status[provider.name].rate_limited = True
                logger.warning(
                    "provider %s attempt %d/%d failed: %s",
                    provider.name, attempt + 1, max_retries + 1, e,
                )
                if attempt < max_retries:
                    time.sleep(backoff_base * (2 ** attempt))
        return [], last_error

    def status_report(self):
        return {name: asdict(s) for name, s in self.status.items()}


_registry_instance = None


def get_registry():
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = ProviderRegistry()
    return _registry_instance
