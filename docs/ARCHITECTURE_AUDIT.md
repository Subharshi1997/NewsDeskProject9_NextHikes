# Architecture Audit

Date: 2026-09-15
Scope: pre-work audit for the "multi-source news aggregation" upgrade request.
No application code was changed to produce this document.

## 1. What this project actually is

A **single-process Streamlit app** — one Python script that is simultaneously
the frontend and the "backend." There is no client/server split, no REST
API, no ORM, and no database server. Total application code (excluding
tests) is ~250 lines across 3 files.

| Layer | Reality |
|---|---|
| Frontend framework | Streamlit (server-rendered widgets, reruns the whole script per interaction) |
| Backend framework | None — Streamlit *is* the backend; there is no separate API server |
| Database | None — the only persistent store is a local JSON file |
| Deployment | None found — no Dockerfile, no CI config, no Procfile, no cloud config. Run via `streamlit run app.py` |
| Package management | `requirements.txt` + a local `venv/`, no lockfile |

## 2. File-by-file inventory

- **[app.py](../app.py)** (141 lines) — the entire UI: query box, language/category
  selectboxes, "Get News" button, result rendering, sidebar history, all in
  one top-to-bottom script executed fresh on every widget interaction.
- **[langchain_config.py](../langchain_config.py)** (65 lines) — all "backend"
  logic:
  - `get_news_articles(query, page_size=10, language="en", category=None)` —
    a single `requests.get` call to Newsdata.io's `/latest` endpoint. No
    retries, no timeout beyond a flat 10s, no backoff, no abstraction —
    Newsdata.io's URL, param names, and response shape (`status`, `results`)
    are hardcoded inline here.
  - `summarize_articles` / `get_summary` — concatenates each article's raw
    `description` field into one text blob.
  - A LangChain `PromptTemplate | ChatGroq` LCEL chain that turns
    `{query, summaries}` into the final analyst-style summary text.
- **[history.py](../history.py)** (39 lines) — the *only* persistence in the
  project. Reads/writes a flat JSON array to `query_history.json`, capped at
  the last 50 entries. Each entry stores `{query, summary, sources, timestamp}`
  where `sources` is `[{title, link}]` — Newsdata's native field names, not a
  normalized schema.
- **tests/** — 12 pytest tests, all unit tests against mocked
  `requests.get` / `lc.newsdata_api_key` / the `history.py` functions. No
  integration or UI tests beyond manual `AppTest` runs done ad hoc during
  development.

## 3. Current Newsdata.io integration (exact location)

`langchain_config.py:27-41`. It is the **only** news source in the project —
there is no NewsAPI, GNews, or RSS code anywhere today. The function is
called from exactly one place: `app.py`'s `fetch_summary_and_articles`
(itself wrapped in `st.cache_data(ttl=900)`).

Downstream code reads Newsdata's raw response fields directly — `article["description"]`,
`article.get("link")`, `article.get("pubDate")`, `article.get("title")` — in
`langchain_config.py`, `app.py`, and `history.py`. There is no normalized
article model anywhere; Newsdata's shape *is* the app's internal shape.

## 4. Database / data model

**There is no database.** No SQL/NoSQL engine, no ORM (no SQLAlchemy,
Django models, Prisma, etc.), no migrations. The closest thing to a data
model is the JSON dict shape written by `history.py`, and even that only
stores *summaries of past queries*, not individual articles — articles are
fetched fresh per query, used once to build a prompt, and discarded (only
their title+link survive, embedded inside that query's history entry).

There is currently no concept of: an article table, a source registry, a
story/cluster, a dedup key, or a quality score.

## 5. Frontend/backend flow

```
User types query + picks language/category
        │
        ▼
"Get News" button click → full Streamlit script rerun
        │
        ▼
fetch_summary_and_articles(query, language, category)   [st.cache_data, 15 min TTL]
        │
        ├─► Newsdata.io /latest  (requests.get, single provider)
        │
        ▼
summarize_articles()  → join descriptions into one string
        │
        ▼
prompt | ChatGroq (openai/gpt-oss-120b) → summary text
        │
        ▼
render: Summary card, download button, Sources card, sidebar history
        │
        ▼
history.py: append {query, summary, sources, timestamp} → query_history.json
```

There are **no REST endpoints** — `GET /api/news` etc. do not exist and
cannot exist without adding a separate API server, since Streamlit doesn't
expose one. This matters for section 15/16 of the request (API endpoints,
provider status endpoint) — those imply infrastructure that isn't present
yet.

## 6. Caching

`st.cache_data(ttl=900)` — in-process memoization inside the single
Streamlit server, keyed on `(query, language, category)`. It is not a real
cache tier (no Redis, no DB-backed cache): it lives only in that one
process's memory, resets on restart, and only helps repeat requests hitting
*that same running process* — fine for local single-user use, not a
multi-instance cache.

## 7. Scheduled/background jobs

None. Every fetch is synchronous and triggered by a button click. There is
no scheduler, no worker process, no cron-equivalent.

## 8. Search/filter functionality

Free-text query (passed straight through as Newsdata's `q` param), a
Language dropdown (6 languages), and a Category dropdown (Newsdata's own 7
categories). No date range, no source filter, no full-text search over
stored data (nothing is stored to search over).

## 9. Environment variables

```
GROQ_API_KEY=
NEWSDATA_API_KEY=
```
Loaded via `python-dotenv`, validated eagerly at module import (raises
`RuntimeError` if either is missing). `.env` is git-ignored;
`.env.example` documents the two variables.

## 10. Deployment configuration

None exists. No containerization, no CI/CD, no process manager config. The
app is started manually (`streamlit run app.py`) for local/dev use.

## 11. Breaking-change surface

Because there is no external API or multi-service contract, "breaking
changes" here mean **internal** ones:

- `app.py` imports `get_news_articles`, `summarize_articles`, `llm_chain`
  directly from `langchain_config.py` by name — any provider-abstraction
  refactor needs to preserve (or update) these call sites.
- `tests/test_langchain_config.py` asserts directly on Newsdata-specific
  internals (`lc.NEWSDATA_URL`, `lc.newsdata_api_key`, the exact `params`
  dict shape) — these tests are coupled to the current single-provider
  implementation and will need rewriting, not just extending, once a
  provider abstraction exists.
- `history.py`'s stored schema (`sources: [{title, link}]`) uses Newsdata's
  field names. If articles are normalized to a schema using `url` instead of
  `link`, `history.py` and the sidebar-rendering code in `app.py` both need
  updating in lockstep, or old `query_history.json` files become unreadable
  by the new renderer. (No such file currently exists on this machine, so
  there's no live migration to worry about today — but the code should not
  assume that's always true.)
- `app.py`'s rendering code assumes each article dict has `title`/`link`/
  `pubDate` keys specifically — a normalized-schema change touches this file
  too, not just the fetch layer.

## 12. Scale assessment against the requested upgrade

The requested architecture (provider registry with 4 live providers,
SQL database with 6+ tables, URL + semantic dedup, story clustering,
source/article quality scoring, scheduled ingestion, a provider-health
API/dashboard, 6 new documentation files, a full new test matrix) describes
infrastructure this project does not have in any form today: no database,
no backend API server, no background worker, no multi-provider anything.

That's not disqualifying — the request's own Rule 27 says to avoid
overengineering and scale to what the project "genuinely requires" — but it
does mean this is a genuine **build**, not a refactor of existing
infrastructure, for several of the 27 sections (specifically: the database,
the scheduler, and the provider-status API). I've proposed a right-sized
version of each in the follow-up plan (chat message accompanying this
document) that preserves the "simple, modular, testable, configurable"
intent of the request without introducing a DB server, message queue, or
separate API service the project doesn't otherwise need.
