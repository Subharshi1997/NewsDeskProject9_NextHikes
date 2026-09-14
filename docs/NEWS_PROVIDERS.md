# News Providers

## The interface

Every provider implements `providers.base.NewsProvider`:

```python
class NewsProvider(ABC):
    name = "base"

    @property
    def enabled(self):
        """Whether this provider is configured and ready to be called."""
        return True

    @abstractmethod
    def fetch_news(self, query=None, category=None, country=None, language=None, page=None, page_size=10):
        """Return a list of NormalizedArticle."""
```

`fetch_news` must return `providers.base.NormalizedArticle` instances (see
[DATA_PIPELINE.md](DATA_PIPELINE.md) for the schema) -- nothing downstream
of the registry ever looks at a provider's raw response shape.

## Currently implemented

| Provider | File | Needs a key? | Enable/disable | Free-tier notes |
|---|---|---|---|---|
| NewsData.io | `providers/newsdata_provider.py` | `NEWSDATA_API_KEY` | `NEWS_PROVIDER_NEWS_DATA_ENABLED` | — |
| RSS | `providers/rss_provider.py` | No | `NEWS_PROVIDER_RSS_ENABLED` | See "no keyword search" below |
| NewsAPI.org | `providers/newsapi_provider.py` | `NEWS_API_KEY` | `NEWS_PROVIDER_NEWS_API_ENABLED` | Dev-tier license blocks non-localhost production use; `/everything` only covers ~the last month |
| GNews | `providers/gnews_provider.py` | `GNEWS_API_KEY` | `NEWS_PROVIDER_GNEWS_ENABLED` | ~100 requests/day; free-tier "real-time" results are delayed ~12 hours (per the API's own response payload) |

`providers.registry.ProviderRegistry._default_providers()` reads those env
flags (default: all `true`) and only constructs the providers that are
enabled. A provider that's enabled but missing its API key reports
`status="disabled"` at call time (via its own `.enabled` property) rather
than erroring -- see `ProviderRegistry.fetch_all`.

### RSS: no keyword search, by design

RSS feeds expose their latest items, not a search endpoint. `RSSProvider.fetch_news`
pulls each configured feed's latest entries and, if a `query` was given,
filters client-side on whether the query text appears in the title or
summary. This means RSS results for a narrow query (e.g. "Nvidia Q3
earnings call") may legitimately be empty even when the feeds are healthy
-- that's expected, not a bug.

### NewsAPI.org / GNews: top-headlines vs. search

Both providers switch endpoint based on whether a `query` was given:
`fetch_news(query=...)` hits their search endpoint (`/v2/everything`,
`/api/v4/search`); `fetch_news()` with no query hits their top-headlines
endpoint instead, since neither provider's search endpoint accepts an
empty query (NewsAPI's `/everything` 400s outright without one).
NewsAPI's `/top-headlines` additionally 400s unless at least one of
`category`/`country`/`sources`/`q` is present, so `NewsAPIProvider`
defaults to `country="us"` when a caller (e.g. the scheduler's general
sweep) supplies none of those -- verified live in
`test_newsapi_provider_uses_top_headlines_and_defaults_country_without_query`.

### Adding another provider (NewsAPI/GNews were built this way)

1. Create `providers/<name>_provider.py` subclassing `NewsProvider`,
   following the shape of `providers/newsdata_provider.py` or
   `providers/newsapi_provider.py`:
   - `__init__(self, api_key=None, timeout=10)` reading its own env var.
   - `enabled` returns `bool(self.api_key)`.
   - `fetch_news(...)` calls the provider's REST endpoint and returns
     `[self._normalize(item) for item in results]`.
   - `_normalize(item)` maps that provider's response fields onto
     `NormalizedArticle`'s fields (see [DATA_PIPELINE.md](DATA_PIPELINE.md)).
     **Verify the real response shape with a live call first** (curl or a
     one-off `requests.get`) rather than guessing field names from memory
     or documentation that may be stale.
2. Add it to `ProviderRegistry._default_providers()`'s candidate list and
   `enabled_flags` dict.
3. Add the key + flag to `.env.example`.
4. Write `tests/test_providers.py`-style tests mocking the HTTP call.

Nothing else changes: `ProviderRegistry.fetch_all`'s failover/retry logic,
`pipeline.ingest`, `langchain_config.get_news_articles`, and `app.py` all
already treat every provider identically through the interface -- this is
exactly how NewsAPI.org and GNews were added after the initial
NewsData.io + RSS rollout, with zero changes needed outside the two new
provider files, `registry.py`'s candidate list, and config.

## Adding an RSS source

Edit `config/rss_sources.json` -- never hardcode a feed URL in code. Each
entry:

```json
{
  "name": "Publication Name",
  "url": "https://example.com/rss.xml",
  "category": "business",
  "country": "IN",
  "language": "en",
  "quality_score": 5
}
```

**Before adding an entry, verify the feed is actually live** (this project
excluded Reuters from the initial list for exactly this reason -- its
public RSS feeds were discontinued and the URL no longer resolves):

```bash
curl -s -o feed.xml -w "%{http_code}\n" "<the feed url>"
grep -c "<item>" feed.xml   # or <entry> for Atom feeds
```

A `quality_score` here only applies while an article is fetched via RSS.
The same source seen through a different provider (e.g. NewsData.io
returning a CNBC article) is scored from `config/sources.json` instead --
see [DATA_PIPELINE.md](DATA_PIPELINE.md).

`category`/`country`/`language` filter which feeds `RSSProvider.fetch_news`
polls for a given request -- they're not scraped from the feed itself,
since generic RSS/Atom doesn't reliably expose that metadata.
