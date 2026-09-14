# Project Audit

Date: 2026-09-15. Written before any code for the News Intelligence &
Predictive Analytics roadmap was touched, per that request's own
instruction to audit first and wait for confirmation.

## Current Architecture

A single-process **Streamlit app** (frontend and "backend" combined in one
process) backed by **SQLite**, with a **multi-provider news ingestion
pipeline** and an **in-process background scheduler**. No separate REST
API, no web framework, no ORM, no message queue, no containerization. Full
diagram in [ARCHITECTURE.md](ARCHITECTURE.md); the short version:

```
NewsData.io + NewsAPI.org + GNews + RSS
              |
   providers/registry.py (fan-out, retry, failover, status)
              |
   pipeline: validation -> dedup -> clustering -> scoring
              |
           db.py (SQLite)
              |
        +-----+-----+
        |           |
  app.py Search   app.py Latest Stories
  (on-demand)     (background-ingested)
```

`scheduler.py` runs the full pipeline on a timer (default 15 min) in a
background thread inside the same process.

## Technology Stack

| Layer | Choice | Notes |
|---|---|---|
| UI | Streamlit 1.63 | server-rendered, reruns the whole script per interaction |
| LLM | Groq (`langchain-groq`), model `openai/gpt-oss-120b` | via LangChain LCEL (`prompt \| llm`) |
| News APIs | NewsData.io, NewsAPI.org, GNews (all live, real keys) | plain `requests` calls |
| RSS | `feedparser` | 8 sources, each verified live before adding |
| Similarity | Hand-rolled TF-IDF + cosine on `numpy` | no scikit-learn/embeddings |
| DB | SQLite via stdlib `sqlite3` | no ORM |
| Scheduling | Python `threading` (daemon thread) | no cron/worker process |
| Testing | `pytest` | 69 tests, all mocked, no network |
| Secrets | `.env` via `python-dotenv` | git-ignored |

No FastAPI/Django/Flask, no Postgres/MySQL/Redis, no Celery/RQ, no Docker,
no CI, no cloud deployment config, no authentication library, no NLP/ML
library beyond `numpy`.

## Frontend Structure

One file: `app.py` (192 lines). Two tabs (`Search`, `Latest Stories`) and a
sidebar (`Query History`, `Provider Status`). No routing, no separate
pages, no client-side framework — Streamlit's rerun-the-whole-script model.
No `st.query_params`-based deep linking exists yet, which matters for any
roadmap feature wanting a shareable URL (topic pages, entity pages, story
pages).

## Backend Structure

No separate backend service. "Backend" logic is plain Python modules
imported directly into the Streamlit process:

| Module | Responsibility |
|---|---|
| `providers/` | `NewsProvider` interface + 4 implementations + registry |
| `pipeline/` | `validation`, `dedup`, `clustering`, `scoring`, `ingest` |
| `db.py` | SQLite schema + data access |
| `scheduler.py` | background ingestion loop |
| `langchain_config.py` | Groq LLM chain + `get_news_articles` (search path) |
| `history.py` | query-history persistence (separate from the article DB) |
| `logging_config.py` | structured logging, secret redaction |

No REST endpoints exist anywhere — this was a deliberate choice made
earlier in this project's history (documented in `ARCHITECTURE.md`), not
an oversight.

## Database Structure

SQLite (`news.db`), 3 tables, defined in `db.py`:

```
sources  (source_name PK, quality_score, country, category, first_seen, last_seen)
stories  (story_id PK, title, created_at, updated_at, article_count)
articles (id PK, ...NormalizedArticle fields..., canonical_url UNIQUE,
          story_id FK, source_name FK, quality_score, is_primary)
```

Indexes on `published_at`, `source_name`, `story_id`, `category`,
`language`, `country`. Currently holds **116 articles / 113 stories** of
local dev data from this build session — not production-scale, and not
representative of what weeks of continuous ingestion would look like.

No user tables, no entity tables, no topic tables, no sentiment columns,
no `market_data`, no `predictions`, no `news_events`, no alerts/saved
stories tables — none of Phase 2-7's data model exists yet.

## NewsData.io Integration

`providers/newsdata_provider.py` — fully implemented, refactored into the
common `NewsProvider` interface, live-verified against the real API this
session (10 real articles fetched and normalized correctly in the most
recent test run).

## API Endpoints

**None.** No `GET /api/...` routes exist. All access is through direct
Python function calls inside the single Streamlit process
(`db.get_articles`, `db.get_stories`, `get_registry().fetch_all()`, etc.).
Provider health is surfaced via a sidebar panel reading
`ProviderRegistry.status_report()` directly, not through an endpoint.

## Current News Pipeline

Two independent paths, sharing the same pipeline modules — see
[DATA_PIPELINE.md](DATA_PIPELINE.md) for full detail:

1. **On-demand search** — `app.py` Search tab → `langchain_config.get_news_articles`
   → `providers.registry.get_registry().fetch_all()` (all 4 providers,
   failover) → `pipeline.validation` → `pipeline.dedup` → Groq summary.
   Cached 15 min via `st.cache_data`.
2. **Scheduled ingestion** — `scheduler.py`'s background thread →
   `pipeline.ingest.run_ingest_cycle`, which additionally runs
   `pipeline.clustering` and `pipeline.scoring` and persists to SQLite.
   Runs every `NEWS_FETCH_INTERVAL` minutes (default 15).

## Existing Features

- 4 live news providers (NewsData.io, NewsAPI.org, GNews, RSS) behind a
  common interface with per-provider retry/backoff/failover.
- Article normalization to a common schema.
- 3-level deduplication (URL canonicalization, normalized-title exact
  match, TF-IDF cosine semantic similarity), plus a DB-level
  `UNIQUE(canonical_url)` backstop.
- Story clustering (greedy single-link TF-IDF), with a "select the best
  version of a story" step (`pipeline.scoring.select_primary`).
- Source quality scoring (configurable, `config/sources.json`) and a
  composite per-article quality/ranking score (configurable weights,
  `pipeline/scoring.py`).
- Data quality validation (rejects unusable articles, clears impossible
  publish dates), all rules documented.
- SQLite persistence with real indexes/constraints.
- In-process background scheduler, configurable interval.
- Streamlit UI: Search (query + language/category filters → LLM summary +
  sources + download), Latest Stories (browses the clustered DB, "Covered
  by N sources"), sidebar query history + live provider status.
- Structured logging with a secret-redaction filter.
- `.env`-based configuration, `.env.example` kept current, no hardcoded
  keys anywhere.
- 69 passing tests.

## Existing NLP/ML

- **LLM summarization** (Groq, via `langchain_config.py`) — but only for
  ad-hoc search queries, producing one paragraph. Not per-story, not
  cached persistently (only via the 15-min `st.cache_data` TTL), not
  bullet-point formatted, not run during scheduled ingestion.
- **TF-IDF + cosine similarity** — used exclusively for dedup and
  clustering. Not exposed as a retrieval mechanism, not persisted as an
  index, not usable as-is for open-ended question answering (RAG).
- **Nothing else**: no sentiment analysis, no named-entity recognition, no
  embeddings model, no vector store, no topic modeling, no forecasting/ML
  model of any kind.

## Existing Authentication

**None.** No user accounts, no login flow, no session-based identity, no
user table. This was explicitly scoped out early in this project ("Task
7.1: Add User Authentication" was marked an optional enhancement and never
built). Every Phase 4 (personalization) feature has no identity to attach
to yet.

## Existing Analytics

**None as a UI feature.** The raw data to power volume/source/category
aggregation already exists in SQLite (`db.get_articles`, `db.get_stories`),
but there is no dashboard, no charts, no trends-over-time view, no country
heatmap, and (since no sentiment data exists) no sentiment trend is even
computable yet.

## Existing Export/Download

One thing: a single search result's LLM summary can be downloaded as a
`.txt` file (`st.download_button` in `app.py`). No CSV/Excel/PDF/JSON
export, and no bulk export of search results, stories, or analytics.

## Existing Tests

69 tests (`pytest tests/ -v`), all mocked/isolated, covering: all 4
providers (normalization, retry, failover), all 3 dedup levels,
clustering, scoring, validation, DB persistence, the `langchain_config`
delegation layer, and query history. Nothing exists yet for Phase 2-7
features since none of that code exists yet.

## Known Problems

- No pagination anywhere — Search and Latest Stories always fetch a fixed
  page size.
- `pipeline.scoring`'s "originality" ranking can be noisy when multiple
  articles in a cluster share the same (or missing) timestamp — documented
  as an accepted trade-off, not a bug.
- Sustained scheduled ingestion has only been observed over a single dev
  session (a few cycles), not over days — retry/backoff tuning is
  reasonable but not battle-tested at that timescale.
- SQLite has no real concurrent-write story for multi-instance deployment
  (fine for the current single-user local use case; flagged already in
  `ARCHITECTURE_AUDIT.md`/`ARCHITECTURE.md`).

## Technical Debt Relevant to This Roadmap

- **No REST API layer.** Several roadmap features (shareable topic/entity/
  story pages, a natural-language search that returns structured results,
  export "pages") are naturally built as routes; Streamlit's
  rerun-the-whole-script model will make deep-linkable pages awkward
  without either `st.query_params`-based routing or restructuring into a
  multi-page Streamlit app.
- **No auth.** Every Phase 4 feature (saved stories, alerts, following, a
  personalized feed) needs an identity model designed from scratch — there
  is nothing to extend.
- **No embeddings/vector store.** RAG (section 26) needs new retrieval
  infrastructure; the existing TF-IDF vectors are computed fresh per
  ingestion batch and discarded, not persisted as a queryable index, and
  TF-IDF is a materially weaker retrieval signal for open-ended natural-
  language questions than embeddings would be.
- **No time-series feature store.** Predictive analytics (Phase 6) needs a
  new pipeline stage — rolling volume/growth-rate aggregation doesn't
  exist yet even as raw numbers, let alone as ML-ready features.
- **No market data integration in any form.** Phase 7 needs an entirely
  new external API integration plus an entity-to-ticker mapping that
  doesn't exist.
- **Limited historical data.** The DB currently holds a few hours of
  ingestion from this dev session. Any of Phase 6's "time-based/walk-
  forward validation" requirements need meaningfully more historical data
  than exists today to produce a validated (not just fitted) model — this
  is a real sequencing constraint, not a code gap.

See [FEATURE_ROADMAP_STATUS.md](FEATURE_ROADMAP_STATUS.md) for the
feature-by-feature comparison against the full roadmap.
