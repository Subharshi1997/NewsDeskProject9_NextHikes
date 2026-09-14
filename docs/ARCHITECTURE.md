# Architecture

See [ARCHITECTURE_AUDIT.md](ARCHITECTURE_AUDIT.md) for what this project
looked like *before* this upgrade. This document describes the system as it
stands now.

## Overview

```
                          NEWS SOURCES
                              |
       +------------+------------+------------+
       |            |            |            |
 NewsData.io    NewsAPI.org    GNews       RSS feeds
       |            |            |      (config/rss_sources.json)
       +------------+------------+------------+
                      |
         providers/registry.py  (fan-out, retry+backoff, failover,
                      |           per-provider status)
                      v
         pipeline/validation.py  (drop unusable articles, clear
                      |           impossible dates)
                      v
         pipeline/dedup.py       (URL -> title -> TF-IDF semantic)
                      |
                      v
         pipeline/clustering.py  (group into stories)
                      |
                      v
         pipeline/scoring.py     (source + article quality,
                      |           pick each story's primary article)
                      v
                    db.py        (SQLite: sources / stories / articles)
                      |
         +------------+------------+
         |                         |
   app.py "Search" tab       app.py "Latest Stories" tab
   (on-demand, LLM summary)  (browses what scheduler.py ingested)
```

Two independent paths use the same pipeline modules:

1. **On-demand search** (`app.py`'s Search tab -> `langchain_config.get_news_articles`
   -> `providers.registry.get_registry().fetch_all()` -> `pipeline.validation`
   -> `pipeline.dedup` -> Groq summary). This is the original feature,
   upgraded in place: it was single-provider before, it's multi-provider
   with dedup and failover now, and callers didn't have to change (see
   "Backward compatibility" below).
2. **Scheduled ingestion** (`scheduler.py`'s background thread ->
   `pipeline.ingest.run_ingest_cycle`, which runs the *full* pipeline --
   validation, dedup, clustering, scoring -- and persists to SQLite). This
   is new; it powers the "Latest Stories" tab and the provider-status
   sidebar panel.

## Why these specific choices

[ARCHITECTURE_AUDIT.md](ARCHITECTURE_AUDIT.md) section 12 covers this in
detail; the short version:

- **SQLite via stdlib `sqlite3`, no ORM.** This app is single-user and
  local. A database server or ORM would be infrastructure the project
  doesn't need yet.
- **In-process background thread for scheduling, not an external cron/
  worker.** Chosen explicitly by the project owner over a standalone
  script, despite the fragility Streamlit's rerun model usually causes for
  background threads -- mitigated with a module-level singleton guard (see
  `scheduler.py`'s docstring on `start_background_ingestion`).
- **No separate REST API.** Provider status and story data are read
  directly from `db.py`/`providers/registry.py` inside `app.py` (the
  sidebar, the Latest Stories tab) instead of through `GET /api/...`
  endpoints, since Streamlit has no REST layer and adding one would mean a
  second running service.
- **TF-IDF + cosine similarity (hand-rolled on `numpy`), not sentence
  embeddings or scikit-learn.** `numpy` is already a transitive dependency
  (via Streamlit/pandas); embeddings would add a much heavier dependency
  and (for local CPU inference) real latency for a marginal accuracy gain
  at this scale.

## Backward compatibility

`app.py`'s Search tab calls `langchain_config.get_news_articles(query, ...)`
exactly as it did before this upgrade -- same signature, same return shape
(a list of dicts with `title`/`description`/`link`/`pubDate`/...). That
function's internals changed completely (single Newsdata call ->
multi-provider fetch + validate + dedup), but nothing importing it needed
to change. `history.py` and the summary/download rendering in `app.py`
are similarly untouched.

## File map

| Path | Responsibility |
|---|---|
| `providers/base.py` | `NewsProvider` interface, `NormalizedArticle` schema |
| `providers/newsdata_provider.py` | NewsData.io -> NormalizedArticle |
| `providers/rss_provider.py` | Configured RSS feeds -> NormalizedArticle |
| `providers/newsapi_provider.py` | NewsAPI.org -> NormalizedArticle |
| `providers/gnews_provider.py` | GNews -> NormalizedArticle |
| `providers/registry.py` | Fan-out, retry/backoff, failover, status tracking |
| `pipeline/validation.py` | Section 20 data quality rules |
| `pipeline/dedup.py` | 3-level deduplication |
| `pipeline/clustering.py` | Story grouping |
| `pipeline/scoring.py` | Source + article scoring, primary-article selection |
| `pipeline/ingest.py` | Orchestrates the full pipeline for scheduled runs |
| `db.py` | SQLite schema + data access |
| `scheduler.py` | In-process background ingestion loop |
| `logging_config.py` | Structured logging, secret redaction |
| `config/rss_sources.json` | RSS source registry (Rule: never hardcode feed URLs) |
| `config/sources.json` | Source quality scores |
| `langchain_config.py` | Groq LLM chain + the (now multi-source) `get_news_articles` |
| `app.py` | Streamlit UI: Search tab, Latest Stories tab, sidebar |
