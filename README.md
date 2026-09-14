# News Research Tool

A Streamlit news app styled as an editorial site (serif headlines, a real
masthead, article thumbnails) with six sections: a **Home** front page
(hero story + ranked grid + trending highlights), **Search** (query → an
LLM-generated summary with sources), **Latest Stories** (the full
filterable, exportable, deduplicated/clustered corpus), **Saved** (stories
you've bookmarked, persisted locally), **Trending** (topics gaining real
momentum — growth, volume, recency, source diversity, not just raw
counts), and **Analytics** (volume/sentiment trends, source comparisons,
per-topic drill-downs, a country heatmap).

News comes from a **multi-source pipeline** — NewsData.io, NewsAPI.org,
GNews, and RSS feeds, deduplicated across all four (see
[docs/NEWS_PROVIDERS.md](docs/NEWS_PROVIDERS.md)) — enriched with
**sentiment analysis and entity extraction** during background ingestion
(see [docs/NLP.md](docs/NLP.md)), then clustered into stories with an
AI-generated summary, timeline, cross-source comparison, coverage
perspective, and "why this matters" note (see
[docs/STORY_INTELLIGENCE.md](docs/STORY_INTELLIGENCE.md)). Full
architecture in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); a full audit
of this project against a 57-feature news-intelligence roadmap is in
[docs/PROJECT_AUDIT.md](docs/PROJECT_AUDIT.md) /
[docs/FEATURE_ROADMAP_STATUS.md](docs/FEATURE_ROADMAP_STATUS.md).

## How it works

1. **`app.py`** — Streamlit UI. All story-card rendering (thumbnail,
   category pills, sentiment badge, summary, why-it-matters, the
   timeline/comparison/perspective expander, related stories, a save
   button, and the full article list) goes through one shared
   `render_story_card` component, used by Home (hero + grid), Latest
   Stories (filterable grid), and Saved — so the same story looks and
   behaves identically everywhere it appears.
2. **`providers/`** — one class per news source (`NewsDataProvider`,
   `RSSProvider`, `NewsAPIProvider`, `GNewsProvider`), all implementing a
   common `NewsProvider` interface, fanned out by `providers/registry.py`
   with per-provider retry/backoff and failover.
3. **`pipeline/`** — `validation` (drop unusable articles), `dedup` (URL →
   title → semantic, 3 levels), `clustering` (group into stories),
   `sentiment` + `entities` (NLP enrichment), `scoring` (source + article
   quality/importance, pick each story's best article), `trending` (topic
   momentum). `pipeline/ingest.py` runs the full chain for scheduled
   ingestion; `langchain_config.get_news_articles` runs the lighter
   fetch+validate+dedup part for on-demand search (see
   [docs/NLP.md](docs/NLP.md) for why NLP enrichment is ingestion-only).
4. **`db.py`** — SQLite persistence (sources/stories/articles/entities/
   article_entities) for everything the background job ingests.
5. **`scheduler.py`** — an in-process background thread that runs the full
   pipeline every `NEWS_FETCH_INTERVAL` minutes.
6. **`langchain_config.py`** — Groq LLM chains: one for on-demand search
   summaries, one for per-story bullet-point AI summaries (cached, only
   for multi-source stories).
7. **`history.py`** — persists past *searches* (not the ingested article
   database) to `query_history.json`.
8. **`saved_stories.py`** — persists bookmarked story IDs locally to
   `saved_stories.json`, same single-local-user pattern as `history.py`.

## Features

- **Multi-source, deduplicated** — 4 providers, cross-provider duplicates
  collapsed into one (see [docs/DEDUPLICATION.md](docs/DEDUPLICATION.md)).
- **Story clustering** — groups articles covering the same event (see
  [docs/STORY_CLUSTERING.md](docs/STORY_CLUSTERING.md)).
- **Sentiment analysis** — every ingested article gets a positive/neutral/
  negative label + confidence (transformer model), rolled up per story.
- **Entity extraction** — people, organizations, places, products, etc.
  (spaCy), shown as tags per article and used to power Trending.
- **AI story summaries** — 3-5 bullet points per multi-source story,
  generated once and cached, not regenerated every cycle.
- **Story intelligence** — for "major" stories (3+ sources): a
  chronological timeline of how coverage developed, a per-source
  cross-source comparison, a coverage-perspective read on tone/emphasis
  per source (clearly labeled as automated analysis, not a bias
  determination), and a "why this matters" note — all from one
  consolidated Groq call (see [docs/STORY_INTELLIGENCE.md](docs/STORY_INTELLIGENCE.md)).
- **Related stories** — each story links to others sharing extracted
  entities with it, ranked by overlap, reusing entity data rather than
  needing new infrastructure.
- **Saved stories** — a ☆ Save button on every story, persisted locally
  (no login — this is a single-local-user tool) and browsable in the
  Saved tab.
- **Editorial design** — serif headlines, a real masthead, article
  thumbnails, category pills, and a hero-story front page, instead of
  Streamlit's default look.
- **Optional access gate** — a shared-password lock (`st.secrets`) for the
  whole app, off by default; see [docs/RUNBOOK.md](docs/RUNBOOK.md)
  "Authentication."
- **Trending topics** — ranked by growth + volume + recency + source
  diversity, not just raw counts, across 24h/7d/30d windows.
- **Importance/quality score** — configurable weighted score (source
  quality, recency, completeness, originality, source diversity, entity
  substance) picks each story's best article.
- **Analytics dashboard** — volume over time, sentiment trends, sortable
  source comparisons, per-topic drill-downs, and a country heatmap (see
  [docs/ANALYTICS.md](docs/ANALYTICS.md)) — including real data cleanup
  for country/category fields some providers jam multiple values into.
- **Provider failover** — a provider that's down, rate-limited, or
  unconfigured is skipped, not fatal; status visible live in the sidebar.
- **Loading feedback & graceful errors** everywhere API/LLM calls happen.
- **Query filters, export, and history** — language/category filters on
  Search; category/sentiment/source/date-range filters on Latest Stories
  (roadmap "Smart Search"); CSV/JSON export of search sources and filtered
  stories, plus `.txt` summary download; browsable query history.

## Setup

```bash
# 1. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

# 2. Install PyTorch (CPU) first, then the rest -- see requirements.txt
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
python -m spacy download en_core_web_sm

# 3. Add your API keys
copy .env.example .env         # Windows
# cp .env.example .env         # macOS/Linux
# then edit .env -- see .env.example for the full list
```

Get a Groq key from https://console.groq.com/keys, a Newsdata.io key from
https://newsdata.io/register, a NewsAPI.org key from
https://newsapi.org/register, and a GNews key from https://gnews.io/register.
`GROQ_API_KEY` is required (no fallback LLM); the three news-provider keys
are each optional — any that's missing just makes that one provider report
`disabled`, and the rest (including RSS, which needs no key at all) keep
working. No key is ever hardcoded — `langchain_config.py`/the providers
load them from `.env` via `python-dotenv`, and `.env` is git-ignored.

The sentiment and entity-extraction models download automatically on first
use (a few hundred MB total, cached locally afterward) — no key needed.

**Optional: password-protect the app** (original spec Task 7.1) — copy
`.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and set
`app_password`. Skip this and the app runs unprotected (the default) —
see [docs/RUNBOOK.md](docs/RUNBOOK.md) "Authentication" for exact behavior.

## Run

```bash
streamlit run app.py
```

**Search tab:** enter a query, optionally adjust filters, click **Get News**.

**Latest Stories tab:** browses what the background job has ingested —
empty for the first cycle after a fresh start (model loading + first fetch
takes under a minute) until it completes (see [docs/RUNBOOK.md](docs/RUNBOOK.md)).

**Analytics tab:** volume/sentiment trends, source comparisons, topic
drill-downs, and a country heatmap — needs some ingestion history to be
meaningful.

**Trending tab:** pick a window (24h/7d/30d); needs a few ingestion cycles
of history to have anything meaningful to rank.

## Test

```bash
pytest tests/ -v
```

161 tests, all mocked/isolated — no live API keys, network calls, or the
sentiment/NER models themselves needed to run. Covers all four providers,
the full pipeline (validation, dedup, clustering, sentiment, entities,
scoring, trending, story timeline/comparison/why-matters generation),
analytics aggregations (including country/category normalization), DB
persistence, the `langchain_config` delegation layer, and query history.

## Project structure

```
news_research_tool/
├── app.py                     # Streamlit UI
├── langchain_config.py        # Multi-source fetch + Groq/LangChain summarization
├── history.py                 # query history persistence (query_history.json)
├── saved_stories.py            # saved-story persistence (saved_stories.json)
├── auth.py                     # optional shared-password gate (st.secrets)
├── db.py                      # SQLite schema + data access
├── analytics.py                # Phase 3: volume/sentiment/source/topic/country aggregation
├── scheduler.py                # in-process background ingestion loop
├── logging_config.py           # structured logging, secret redaction
├── providers/
│   ├── base.py                 # NewsProvider interface, NormalizedArticle schema
│   ├── registry.py              # fan-out, retry/backoff, failover, status
│   ├── newsdata_provider.py
│   ├── rss_provider.py
│   ├── newsapi_provider.py
│   └── gnews_provider.py
├── pipeline/
│   ├── validation.py            # data quality rules
│   ├── dedup.py                 # URL / title / semantic deduplication
│   ├── clustering.py            # story grouping
│   ├── sentiment.py              # transformer sentiment classification
│   ├── entities.py               # spaCy entity extraction
│   ├── scoring.py                # source + article quality/importance scoring
│   ├── trending.py               # topic momentum ranking
│   └── ingest.py                 # orchestrates the full pipeline
├── config/
│   ├── rss_sources.json          # RSS source registry (verified feeds only)
│   └── sources.json               # source quality scores
├── docs/
│   ├── PROJECT_AUDIT.md           # audit against the news-intelligence roadmap
│   ├── FEATURE_ROADMAP_STATUS.md  # feature-by-feature gap analysis
│   ├── ARCHITECTURE_AUDIT.md      # earlier pre-multi-source audit
│   ├── ARCHITECTURE.md
│   ├── NEWS_PROVIDERS.md
│   ├── DATA_PIPELINE.md
│   ├── DEDUPLICATION.md
│   ├── STORY_CLUSTERING.md
│   ├── NLP.md                     # sentiment, entities, importance, summaries, trending
│   ├── ANALYTICS.md               # volume/sentiment/source/topic/country dashboards
│   ├── STORY_INTELLIGENCE.md      # timeline, cross-source comparison, why this matters
│   └── RUNBOOK.md
├── requirements.txt
├── pytest.ini
├── .env.example
├── .streamlit/
│   ├── config.toml               # editorial theme
│   └── secrets.toml.example      # copy to secrets.toml to enable the access gate
├── .gitignore
└── tests/
    ├── conftest.py
    ├── test_langchain_config.py
    ├── test_history.py
    ├── test_providers.py
    ├── test_dedup.py
    ├── test_clustering.py
    ├── test_scoring.py
    ├── test_validation.py
    ├── test_sentiment.py
    ├── test_entities.py
    ├── test_trending.py
    ├── test_analytics.py
    ├── test_ingest.py
    ├── test_saved_stories.py
    ├── test_auth.py
    └── test_db.py
```

## Notes on deviations from a minimal setup

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) "Why these specific
choices" and [docs/NLP.md](docs/NLP.md) for full reasoning. Highlights:

- SQLite not a DB server, in-process scheduler not external cron, no
  separate REST API, hand-rolled TF-IDF (dedup/clustering) not embeddings.
- Sentiment/entities use proper models (a transformer, spaCy) rather than
  lightweight rule-based alternatives — a deliberate choice favoring
  accuracy over dependency weight, made explicitly by the project owner.
- NLP enrichment and AI summaries run only during background ingestion,
  never on a page load — the Search tab stays fast and lightweight.
- `GROQ_API_KEY` is required at import time (no fallback LLM); the three
  news-provider keys are not — providers degrade gracefully instead.
- Query history (`query_history.json`), saved stories (`saved_stories.json`),
  and the article database (`news.db`, SQLite) are all git-ignored local
  files, not shared state — this is a single-local-user tool by design.

## Validation status

- Unit tests: `pytest tests/ -v` — 161/161 passing (mocked, no network, no
  ML models needed).
- Live end-to-end runs (real keys, real models, real Groq calls): full
  4-provider ingestion with sentiment/entity enrichment verified directly
  — real sentiment labels, 224+ distinct entities extracted with correct
  cross-article mention-count aggregation, real AI-generated story
  summaries cached correctly, trending correctly ranked real growing
  entities. All 5 Analytics sections click-tested against the real DB with
  no errors, and the country/category normalization verified against
  actual messy production values (comma-separated multi-country fields,
  mixed ISO codes and full names). Story timeline/cross-source comparison/
  coverage perspective/why-this-matters verified with a real 3-source test
  story — accurate chronological ordering, correctly distinguished each
  source's actual focus and tone, the required disclaimer reproduced
  verbatim, and a grounded significance summary. The redesigned Home/
  Latest Stories/Saved tabs click-tested end to end: hero + grid render,
  the Save button correctly persists to disk and the saved state survives
  a full process restart, category pills and related-stories rendering
  confirmed on a seeded example. The auth gate click-tested end to end
  with a real configured password: unprotected by default, fully blocks
  all 6 tabs when a password is set, rejects a wrong one with an error
  while staying locked, and unlocks correctly on the right one.
- Two real bugs found by this live testing (not unit tests, which use
  fresh temp DBs/mocked data every time) and fixed: a schema-migration
  ordering bug (new columns not being added to an already-existing
  `news.db` before an index tried to reference them), and `category`
  values with the same multi-value-jammed-into-one-field problem as
  `country` producing bogus compound categories.
- App boot: `streamlit run app.py` starts cleanly, serves HTTP 200, and the
  background scheduler completes full-pipeline ingestion cycles (fetch →
  validate → dedup → sentiment → entities → cluster → score → summarize →
  store) with no errors in the log.

## Optional enhancements (not implemented)

All three of the original spec's optional enhancements are now built —
see "Authentication" below for the last one (Task 7.1).
