# Runbook

## Environment variables

See `.env.example` for the authoritative, current list. Summary:

| Variable | Required? | Purpose |
|---|---|---|
| `GROQ_API_KEY` | Yes | LLM summarization (no fallback provider) |
| `NEWSDATA_API_KEY` | No* | NewsData.io provider. Without it, that provider reports `disabled` and the app runs on RSS alone. |
| `NEWS_PROVIDER_NEWS_DATA_ENABLED` | No (default `true`) | Force-disable NewsData.io even if a key is present |
| `NEWS_PROVIDER_RSS_ENABLED` | No (default `true`) | Force-disable RSS |
| `NEWS_FETCH_INTERVAL` | No (default `15`) | Minutes between background ingestion cycles |
| `NEWS_DB_PATH` | No (default `./news.db`) | SQLite file location |

\* Not required to *start* the app (unlike before this upgrade) -- the
provider registry degrades gracefully. It's required for the app to be
useful with only RSS, though: RSS can't do keyword search (see
[NEWS_PROVIDERS.md](NEWS_PROVIDERS.md)).

`NEWS_API_KEY` / `GNEWS_API_KEY` and their enable flags are in
`.env.example`, commented out -- they take effect once those providers are
implemented (see [NEWS_PROVIDERS.md](NEWS_PROVIDERS.md) "Adding a new
provider").

## Running the app

```bash
venv\Scripts\activate          # Windows; source venv/bin/activate elsewhere
pip install -r requirements.txt
copy .env.example .env         # then fill in GROQ_API_KEY (+ NEWSDATA_API_KEY)
streamlit run app.py
```

On startup, `app.py` calls `db.init_db()` (idempotent -- creates the
SQLite schema if it doesn't exist) and `scheduler.start_background_ingestion()`
(idempotent -- see below).

## The background scheduler

A daemon thread inside the Streamlit process, started once per server
process (not per browser tab -- see `scheduler.py`'s docstring on the
module-level guard it uses instead of `st.session_state`). Every
`NEWS_FETCH_INTERVAL` minutes it runs the full pipeline
(`pipeline.ingest.run_ingest_cycle`) with no specific query -- a general
sweep across every enabled provider's top/latest feed -- and stores results
in SQLite. This is what populates the "Latest Stories" tab.

**Checking it's alive:** the sidebar's "Provider Status" section shows
"Background ingestion: running/stopped" plus each provider's last
success/failure, response time, and articles fetched on its most recent
run. `scheduler.is_running()` is the same check programmatically.

**It silently produces nothing for a while on a fresh install** -- the
first cycle needs to complete (a few seconds to ~10s depending on network)
before the Latest Stories tab has anything to show. The tab says as much.

## Inspecting the database directly

```bash
python -c "import db; print(len(db.get_articles(limit=1000)), 'articles')"
python -c "import db; [print(s['title'], s['article_count']) for s in db.get_stories(limit=10)]"
```

Or with the `sqlite3` CLI: `sqlite3 news.db ".tables"`,
`select * from stories order by updated_at desc limit 5;`.

## Testing

```bash
pytest tests/ -v
```

59 tests, all mocked/isolated -- no live API keys or network calls needed.
Coverage: providers (normalization, failover, retry), dedup (all 3
levels), clustering, scoring, validation, DB persistence, the
`langchain_config` delegation layer, and history persistence.

## Troubleshooting

**A provider shows `disabled` in the sidebar.** Check its API key is set
(`NEWSDATA_API_KEY`) and its enable flag isn't `false`
(`NEWS_PROVIDER_NEWS_DATA_ENABLED` / `_RSS_ENABLED`).

**A provider shows `error`.** Expand its sidebar entry for the last error
message. Retries (2, with exponential backoff) already happened before
this was reported -- see `providers/registry.py`'s `_fetch_with_retry`.
This does not stop other providers or crash the app.

**RSS provider is `ok` but contributes 0 articles for a search.** Expected
for narrow queries -- see [NEWS_PROVIDERS.md](NEWS_PROVIDERS.md)'s note on
RSS not supporting real keyword search.

**One RSS source is broken but others work.** `RSSProvider.fetch_news`
catches per-source exceptions and logs+skips (see `logging_config.py`'s
output) rather than failing the whole provider -- check the log for
`rss: failed to fetch source ...`.

**"Latest Stories" tab is empty.** Either the first scheduled cycle hasn't
completed yet (see above), or `NEWS_FETCH_INTERVAL` is long and it's been
a while since the process started -- check the sidebar's "last success"
timestamp for either provider.

**Search results look stale.** `app.py`'s `fetch_summary_and_articles` is
`st.cache_data`-cached for 15 minutes per exact `(query, language,
category)` tuple, to avoid re-hitting Newsdata.io/Groq on every rerun.
Wait out the TTL or change a filter to force a fresh fetch.

## Authentication

Original project spec Task 7.1: "restrict access to authorized users
only." For a single-local-user tool, a full account system (user table,
password hashing, sessions) is more infrastructure than this needs -- it's
a shared-password gate instead, using Streamlit's own `st.secrets`
mechanism.

**Setup:**
```bash
copy .streamlit\secrets.toml.example .streamlit\secrets.toml   # Windows
# cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # macOS/Linux
# then edit secrets.toml and set app_password to a real value
```

`.streamlit/secrets.toml` is git-ignored (same as `.env`). Restart the app
after creating/editing it.

**Behavior:**
- No `secrets.toml`, or `app_password` unset/empty: the app runs
  **unprotected** -- this is the default, deliberate so a fresh local
  clone is never locked out before anyone's configured a password. There
  is no warning banner for this state; the absence of a password gate on
  a local dev machine is expected, not a misconfiguration.
- `app_password` set: every session must enter it once (a form, not a
  raw text box, so Enter submits) before any tab renders. A wrong
  password shows an error and stays gated. A correct one sets
  `st.session_state.authenticated` and unlocks the session until the
  browser tab is closed or "🔒 Log out" (top of the sidebar, only shown
  when a password is configured) is clicked.
- The background ingestion scheduler runs regardless of auth state --
  the gate protects the UI, not data collection, since there's no reason
  to pause the one behind the scenes while nobody's looking at the front.

**What this is not:** multiple accounts, per-user permissions, or
anything password-hashed/salted -- it's one shared secret compared with
`==`, appropriate for "keep casual visitors off my locally-run app," not
for exposing this app on the open internet with real access-control needs.

## Logging

`logging_config.configure_logging()` sets up one root logger
(`news_research_tool`) with a `SecretRedactingFilter` that best-effort
redacts any log message referencing a credential-like field name. Every
module logs under `news_research_tool.<module>` (e.g.
`news_research_tool.providers.newsdata`) so you can filter by subsystem.
