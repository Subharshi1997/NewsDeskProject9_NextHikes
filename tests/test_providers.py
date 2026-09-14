from unittest.mock import Mock, patch

import pytest

from providers.base import NormalizedArticle
from providers.gnews_provider import GNewsProvider
from providers.newsapi_provider import NewsAPIProvider
from providers.newsdata_provider import NewsDataProvider
from providers.registry import ProviderRegistry
from providers.rss_provider import RSSProvider


class FakeProvider:
    def __init__(self, name, articles=None, error=None, enabled=True):
        self.name = name
        self._articles = articles or []
        self._error = error
        self.enabled = enabled
        self.calls = 0

    def fetch_news(self, **kwargs):
        self.calls += 1
        if self._error:
            raise self._error
        return self._articles


def make_article(**overrides):
    defaults = dict(article_id="1", title="Title", url="https://example.com/a", provider="fake", source_name="Fake Source")
    defaults.update(overrides)
    return NormalizedArticle(**defaults)


def _fake_feed(entries):
    feed = Mock()
    feed.entries = entries
    return feed


# --- NewsDataProvider ---


def test_newsdata_provider_normalizes_response():
    provider = NewsDataProvider(api_key="test-key")
    fake_payload = {
        "status": "success",
        "results": [
            {
                "article_id": "abc123",
                "title": "Some Title",
                "link": "https://example.com/story?utm_source=x",
                "description": "A description.",
                "content": "ONLY AVAILABLE IN PAID PLANS",
                "pubDate": "2026-09-07 18:16:00",
                "source_id": "cnbc",
                "creator": ["Jane Doe"],
                "language": "english",
                "country": ["united states of america"],
                "category": ["business"],
                "keywords": ["ai", "chips"],
            }
        ],
    }
    fake_response = Mock(json=Mock(return_value=fake_payload))
    fake_response.raise_for_status = Mock()

    with patch("providers.newsdata_provider.requests.get", return_value=fake_response) as mock_get:
        articles = provider.fetch_news(query="nvidia", page_size=10)

    assert mock_get.call_args.kwargs["params"]["apikey"] == "test-key"
    assert mock_get.call_args.kwargs["params"]["q"] == "nvidia"
    assert len(articles) == 1
    article = articles[0]
    assert isinstance(article, NormalizedArticle)
    assert article.title == "Some Title"
    assert article.url == "https://example.com/story?utm_source=x"
    assert article.provider == "newsdata"
    assert article.source_name == "cnbc"
    assert article.content is None
    assert article.author == "Jane Doe"
    assert article.published_at == "2026-09-07T18:16:00+00:00"
    assert article.category == "business"


def test_newsdata_provider_disabled_and_raises_without_api_key(monkeypatch):
    # Other test modules import langchain_config, whose load_dotenv() call
    # populates the real NEWSDATA_API_KEY into the process environment for
    # the rest of the pytest run -- force a clean environment here so this
    # test doesn't depend on module import order.
    monkeypatch.delenv("NEWSDATA_API_KEY", raising=False)
    provider = NewsDataProvider(api_key=None)
    assert provider.enabled is False
    with pytest.raises(RuntimeError):
        provider.fetch_news(query="x")


def test_newsdata_provider_raises_on_error_status():
    provider = NewsDataProvider(api_key="test-key")
    fake_response = Mock(json=Mock(return_value={"status": "error", "message": "bad"}))
    fake_response.raise_for_status = Mock()
    with patch("providers.newsdata_provider.requests.get", return_value=fake_response):
        with pytest.raises(RuntimeError):
            provider.fetch_news(query="x")


# --- RSSProvider ---


def test_rss_provider_normalizes_and_respects_page_size(tmp_path):
    sources_file = tmp_path / "rss_sources.json"
    sources_file.write_text(
        '[{"name": "Test Feed", "url": "https://example.com/rss", '
        '"category": "business", "country": "IN", "language": "en", "quality_score": 5}]',
        encoding="utf-8",
    )
    provider = RSSProvider(sources_file=sources_file)

    entry = {
        "id": "guid-1",
        "title": "Nvidia beats earnings",
        "link": "https://example.com/story-1",
        "summary": "Nvidia posted strong results.",
        "author": "Reporter",
        "published_parsed": (2026, 9, 7, 18, 0, 0, 0, 0, 0),
        "tags": [{"term": "markets"}],
    }
    with patch("providers.rss_provider.feedparser.parse", return_value=_fake_feed([entry])):
        articles = provider.fetch_news(query="nvidia", page_size=10)

    assert len(articles) == 1
    article = articles[0]
    assert article.title == "Nvidia beats earnings"
    assert article.source_name == "Test Feed"
    assert article.provider == "rss"
    assert article.category == "business"
    assert article.keywords == ["markets"]
    assert article.published_at == "2026-09-07T18:00:00+00:00"


def test_rss_provider_query_filters_out_non_matching_entries(tmp_path):
    sources_file = tmp_path / "rss_sources.json"
    sources_file.write_text(
        '[{"name": "Test Feed", "url": "https://example.com/rss", "category": "top", '
        '"country": "IN", "language": "en", "quality_score": 5}]',
        encoding="utf-8",
    )
    provider = RSSProvider(sources_file=sources_file)
    entry = {"title": "Unrelated cricket news", "link": "https://example.com/x", "summary": "Cricket."}
    with patch("providers.rss_provider.feedparser.parse", return_value=_fake_feed([entry])):
        articles = provider.fetch_news(query="nvidia")
    assert articles == []


def test_rss_provider_one_bad_source_does_not_break_others(tmp_path):
    sources_file = tmp_path / "rss_sources.json"
    sources_file.write_text(
        '[{"name": "Bad Feed", "url": "https://bad.example.com/rss", "category": "top", '
        '"country": "IN", "language": "en", "quality_score": 5},'
        '{"name": "Good Feed", "url": "https://good.example.com/rss", "category": "top", '
        '"country": "IN", "language": "en", "quality_score": 5}]',
        encoding="utf-8",
    )
    provider = RSSProvider(sources_file=sources_file)
    good_entry = {"title": "Good story", "link": "https://good.example.com/1", "summary": "..."}

    def fake_parse(url):
        if "bad" in url:
            raise ValueError("boom")
        return _fake_feed([good_entry])

    with patch("providers.rss_provider.feedparser.parse", side_effect=fake_parse):
        articles = provider.fetch_news()

    assert len(articles) == 1
    assert articles[0].title == "Good story"


def test_rss_provider_disabled_when_sources_file_missing(tmp_path):
    provider = RSSProvider(sources_file=tmp_path / "does_not_exist.json")
    assert provider.enabled is False


# --- NewsAPIProvider ---


def test_newsapi_provider_normalizes_response():
    provider = NewsAPIProvider(api_key="test-key")
    fake_payload = {
        "status": "ok",
        "totalResults": 1,
        "articles": [
            {
                "source": {"id": "the-verge", "name": "The Verge"},
                "author": "Jane Doe",
                "title": "Nvidia earnings beat",
                "description": "A description.",
                "url": "https://example.com/story",
                "urlToImage": "https://example.com/img.jpg",
                "publishedAt": "2026-08-27T16:20:07Z",
                "content": "Full text here... [+5467 chars]",
            }
        ],
    }
    fake_response = Mock(json=Mock(return_value=fake_payload))
    fake_response.raise_for_status = Mock()

    with patch("providers.newsapi_provider.requests.get", return_value=fake_response) as mock_get:
        articles = provider.fetch_news(query="nvidia earnings", language="en")

    assert mock_get.call_args.args[0] == "https://newsapi.org/v2/everything"
    assert mock_get.call_args.kwargs["params"]["q"] == "nvidia earnings"
    assert len(articles) == 1
    article = articles[0]
    assert article.provider == "newsapi"
    assert article.source_name == "The Verge"
    assert article.published_at == "2026-08-27T16:20:07+00:00"
    assert article.content == "Full text here..."  # truncation marker stripped


def test_newsapi_provider_uses_top_headlines_and_defaults_country_without_query():
    provider = NewsAPIProvider(api_key="test-key")
    fake_response = Mock(json=Mock(return_value={"status": "ok", "articles": []}))
    fake_response.raise_for_status = Mock()

    with patch("providers.newsapi_provider.requests.get", return_value=fake_response) as mock_get:
        provider.fetch_news()

    assert mock_get.call_args.args[0] == "https://newsapi.org/v2/top-headlines"
    assert mock_get.call_args.kwargs["params"]["country"] == "us"


def test_newsapi_provider_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("NEWS_API_KEY", raising=False)
    provider = NewsAPIProvider(api_key=None)
    assert provider.enabled is False
    with pytest.raises(RuntimeError):
        provider.fetch_news(query="x")


def test_newsapi_provider_raises_on_error_status():
    provider = NewsAPIProvider(api_key="test-key")
    fake_response = Mock(json=Mock(return_value={"status": "error", "message": "bad"}))
    fake_response.raise_for_status = Mock()
    with patch("providers.newsapi_provider.requests.get", return_value=fake_response):
        with pytest.raises(RuntimeError):
            provider.fetch_news(query="x")


# --- GNewsProvider ---


def test_gnews_provider_normalizes_response():
    provider = GNewsProvider(api_key="test-key")
    fake_payload = {
        "totalArticles": 1,
        "articles": [
            {
                "id": "abc123",
                "title": "Nvidia earnings beat",
                "description": "A description.",
                "content": "Full text here... [720 chars]",
                "url": "https://example.com/story",
                "image": "https://example.com/img.jpg",
                "publishedAt": "2026-09-09T12:57:35Z",
                "lang": "en",
                "source": {"name": "Seeking Alpha", "url": "https://seekingalpha.com", "country": "us"},
            }
        ],
    }
    fake_response = Mock(json=Mock(return_value=fake_payload))
    fake_response.raise_for_status = Mock()

    with patch("providers.gnews_provider.requests.get", return_value=fake_response) as mock_get:
        articles = provider.fetch_news(query="nvidia earnings")

    assert mock_get.call_args.args[0] == "https://gnews.io/api/v4/search"
    assert len(articles) == 1
    article = articles[0]
    assert article.provider == "gnews"
    assert article.source_name == "Seeking Alpha"
    assert article.country == "us"
    assert article.published_at == "2026-09-09T12:57:35+00:00"
    assert article.content == "Full text here..."


def test_gnews_provider_uses_top_headlines_without_query():
    provider = GNewsProvider(api_key="test-key")
    fake_response = Mock(json=Mock(return_value={"articles": []}))
    fake_response.raise_for_status = Mock()

    with patch("providers.gnews_provider.requests.get", return_value=fake_response) as mock_get:
        provider.fetch_news()

    assert mock_get.call_args.args[0] == "https://gnews.io/api/v4/top-headlines"


def test_gnews_provider_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("GNEWS_API_KEY", raising=False)
    provider = GNewsProvider(api_key=None)
    assert provider.enabled is False
    with pytest.raises(RuntimeError):
        provider.fetch_news(query="x")


def test_gnews_provider_raises_on_error_payload():
    provider = GNewsProvider(api_key="test-key")
    fake_response = Mock(json=Mock(return_value={"errors": ["invalid key"]}))
    fake_response.raise_for_status = Mock()
    with patch("providers.gnews_provider.requests.get", return_value=fake_response):
        with pytest.raises(RuntimeError):
            provider.fetch_news(query="x")


# --- ProviderRegistry failover ---


def test_registry_skips_disabled_providers():
    disabled = FakeProvider("disabled", enabled=False)
    ok = FakeProvider("ok", articles=[make_article()])
    registry = ProviderRegistry(providers=[disabled, ok])

    articles = registry.fetch_all(query="x", max_retries=0)

    assert len(articles) == 1
    assert registry.status["disabled"].status == "disabled"
    assert disabled.calls == 0


def test_registry_continues_when_one_provider_fails():
    failing = FakeProvider("failing", error=RuntimeError("boom"))
    working = FakeProvider("working", articles=[make_article(title="Still works")])
    registry = ProviderRegistry(providers=[failing, working])

    articles = registry.fetch_all(query="x", max_retries=0, backoff_base=0)

    assert len(articles) == 1
    assert articles[0].title == "Still works"
    assert registry.status["failing"].status == "error"
    assert registry.status["working"].status == "ok"


def test_registry_retries_before_giving_up():
    class FlakyProvider(FakeProvider):
        def fetch_news(self, **kwargs):
            self.calls += 1
            if self.calls < 2:
                raise RuntimeError("temporary")
            return self._articles

    flaky = FlakyProvider("flaky", articles=[make_article()])
    registry = ProviderRegistry(providers=[flaky])

    articles = registry.fetch_all(query="x", max_retries=2, backoff_base=0)

    assert len(articles) == 1
    assert flaky.calls == 2
    assert registry.status["flaky"].status == "ok"


def test_default_providers_includes_all_four_when_all_enabled(monkeypatch):
    for flag in (
        "NEWS_PROVIDER_NEWS_DATA_ENABLED", "NEWS_PROVIDER_RSS_ENABLED",
        "NEWS_PROVIDER_NEWS_API_ENABLED", "NEWS_PROVIDER_GNEWS_ENABLED",
    ):
        monkeypatch.delenv(flag, raising=False)

    names = {p.name for p in ProviderRegistry._default_providers()}

    assert names == {"newsdata", "rss", "newsapi", "gnews"}


def test_default_providers_respects_disabled_flag(monkeypatch):
    monkeypatch.setenv("NEWS_PROVIDER_GNEWS_ENABLED", "false")

    names = {p.name for p in ProviderRegistry._default_providers()}

    assert "gnews" not in names
    assert "newsdata" in names
