# Feature Roadmap Status

Compares every feature in the News Intelligence & Predictive Analytics
roadmap against what exists today. See [PROJECT_AUDIT.md](PROJECT_AUDIT.md)
for the full current-state writeup this is based on.

Legend: ✅ implemented · 🟡 partial · ❌ missing · 🔴 broken (nothing found
in this category — no known-broken features).

---

## Phase 1 — Core News Aggregation

| # | Feature | Status | Existing files | Missing / required changes | Priority |
|---|---|---|---|---|---|
| 1 | NewsData.io | ✅ | `providers/newsdata_provider.py` | none | done |
| 2 | NewsAPI | ✅ | `providers/newsapi_provider.py` | none — supports keyword search, category, country, language, pagination; date range not exposed (NewsAPI's `/everything` supports `from`/`to`, not yet wired through `fetch_news`'s signature) | low (date range is the only gap) |
| 3 | GNews | ✅ | `providers/gnews_provider.py` | same date-range gap as NewsAPI | low |
| 4 | RSS | ✅ | `providers/rss_provider.py`, `config/rss_sources.json` | 8 sources across categories (business/world/top), each verified live before adding; could add India/Science/Sports-specific feeds if desired | low |
| 5 | Provider abstraction | ✅ | `providers/base.py`, `providers/registry.py` | naming variance only: existing env vars are `NEWS_PROVIDER_NEWS_DATA_ENABLED` etc. (extra underscore) vs. roadmap's `NEWS_PROVIDER_NEWSDATA_ENABLED` — cosmetic, renaming would be a breaking `.env` change for no functional gain | n/a |
| 6 | Article normalization | ✅ | `providers/base.py` (`NormalizedArticle`) | schema matches the roadmap's field list exactly | done |
| 7 | Deduplication | ✅ | `pipeline/dedup.py` | all 3 levels implemented and tested; DB-level `UNIQUE(canonical_url)` as backstop | done |

**Phase 1 is essentially complete.** The only real gap is date-range
filtering on NewsAPI/GNews, which is a small addition to two existing
files, not new architecture.

---

## Phase 2 — News Intelligence / NLP

**Built this round** (see [NLP.md](NLP.md) for full detail). Per the project
owner's choices: proper models (transformer sentiment + spaCy NER), not
lightweight rule-based ones.

| # | Feature | Status | Existing files | Notes | Priority |
|---|---|---|---|---|---|
| 8 | Story clustering | ✅ | `pipeline/clustering.py` | done previously | done |
| 9 | Trending topics | ✅ | `pipeline/trending.py` | Volume+growth+recency+diversity formula, 24h/7d/30d windows. Operates over extracted *entities*, not full topic modeling (deliberate simplification, see NLP.md) — so thematic phrases like "AI Regulation" won't surface unless also tagged as a named entity | done, with a documented scope limit |
| 10 | Sentiment analysis | ✅ | `pipeline/sentiment.py` | `cardiffnlp/twitter-roberta-base-sentiment-latest` (transformer, 3-class), run during ingestion, persisted per-article, story-level aggregate computed on demand via SQL | done |
| 11 | Entity extraction | ✅ | `pipeline/entities.py`, `entities`/`article_entities` tables | spaCy `en_core_web_sm`. No cross-article entity linking ("Nvidia" vs "NVIDIA Corp" stay distinct) and no ticker/stock extraction (deferred to Phase 7) — documented limitations, not oversights | done, with documented limits |
| 12 | Importance score | ✅ | `pipeline/scoring.py` (`score_article`) | Extended in place (same field as the pre-existing quality score) with `source_diversity_score` + `entity_importance_score`. Entity importance is a crude per-article distinct-count proxy, not a corpus-wide prominence signal — a natural v2 once more ingestion history exists | done, v1 |
| 13 | AI summaries | ✅ | `langchain_config.generate_story_summary`, `pipeline/ingest.py` | 3-5 bullet points + overview sentence, generated only for 2+-article stories, cached permanently in `stories.summary` (never regenerated once set) | done |

Not built in this pass, explicitly out of scope per the roadmap's own
`#42/#43` (topic/entity *pages*, as opposed to the trending/entity *data*
itself, which now exists) — still needs routing (see PROJECT_AUDIT.md's
Technical Debt).

---

## Phase 3 — News Analytics

**Built this round** (see [ANALYTICS.md](ANALYTICS.md) for full detail).

| # | Feature | Status | Notes | Priority |
|---|---|---|---|---|
| 14 | News volume dashboard | ✅ | Today/week/month metrics + 30-day volume chart + top categories/sources | done |
| 15 | Sentiment trends | ✅ | Daily positive/neutral/negative line chart, built on Phase 2's sentiment data | done |
| 16 | Source analytics | ✅ | Sortable table: articles, avg importance, avg sentiment, story coverage. "Trending Coverage" sub-metric not built (would need a heavier cross-reference join) | done, one sub-metric deferred |
| 17 | Topic analytics | ✅ | Per-entity drill-down: volume, growth, sentiment, top sources, historical trend. Same "entities, not topic modeling" scope limit as trending (#9) | done, with the same documented scope limit as #9 |
| 18 | Country heatmap | ✅ | Plotly choropleth. Required real data cleanup: the `country` field mixes 2-letter codes, lowercase full names, and (for some NewsData.io articles) dozens of countries jammed into one comma-separated field. Normalized via `pycountry` + a small alias table; unresolvable values are dropped, not guessed at | done, with documented partial coverage |
| 19 | Historical analysis | 🟡 | Folded into Overview's 30-day volume chart and Topic Analytics' per-entity trend rather than a separate section; weekly/monthly rollup granularity not built (daily only) | done for daily; weekly/monthly deferred |

**A related bug found and fixed along the way**: `category` has the exact
same multi-value-field problem as `country` (NewsData.io sometimes tags
one article `"top, politics"` as a single field) — `db.get_top_categories`
now splits and re-aggregates instead of treating that as its own bogus
compound category.

---

## Phase 4 — Personalization

| # | Feature | Status | Missing components | Priority |
|---|---|---|---|---|
| 20 | User interests | ❌ | No auth exists at all — this is the blocker for all of Phase 4 | blocked on auth decision |
| 21 | Personalized feed | ❌ | Same | blocked on auth decision |
| 22 | Saved stories | ❌ | Same | blocked on auth decision |
| 23 | News alerts | ❌ | Same, plus no email/notification infrastructure exists to reuse | blocked on auth decision |
| 24 | Entity following | ❌ | Same, plus blocked on #11 | blocked on auth + #11 |

**This entire phase is gated on one decision the roadmap itself defers:**
"if authentication does not exist, design this modularly and avoid
introducing a complex auth system unnecessarily." None exists today.
Options range from a single-user `st.secrets` password gate (no real user
model, so most of Phase 4 still wouldn't make sense) to a lightweight
per-browser identity (e.g. a UUID in `st.session_state`/a cookie, no
login) to real accounts (a users table + password hashing, meaningfully
more infrastructure). This needs a decision before any Phase 4 code is
written.

---

## Phase 5 — Advanced AI

**Timeline, cross-source comparison, coverage perspective, and
why-this-matters all built** (see [STORY_INTELLIGENCE.md](STORY_INTELLIGENCE.md))
— 4 of 7 Phase 5 items, none needing a new dependency or design decision.
Chatbot/RAG and fact-check remain deliberately deferred.

| # | Feature | Status | Notes | Priority |
|---|---|---|---|---|
| 25 | News chatbot | ❌ | Entirely new UI + RAG backend | depends on #26 |
| 26 | RAG | ❌ | Project owner chose TF-IDF-only retrieval for when this is built — not yet built. No embeddings, no persisted vector index | deferred, decision already made |
| 27 | Story timeline | ✅ | `langchain_config.generate_story_extras` — a chronological narrative built from articles sorted by `published_at`, not a forced stage taxonomy (the roadmap's example arc fits policy stories, not all story types) | done |
| 28 | Cross-source comparison | ✅ | Same call: one line per source on what angle it emphasized, matching the roadmap's own example format exactly | done |
| 29 | Coverage perspective | ✅ | Folded into the same consolidated Groq call as #27/#28/#30 -- per-source tone/emphasis/word-choice analysis, with an enforced (and UI-repeated) disclaimer that this is automated language-pattern analysis, not a bias determination, per the roadmap's own explicit caution | done |
| 30 | Why This Matters | ✅ | Same call: 2-3 sentences on significance, cached, never regenerated once set | done |
| 31 | Fact-check / verification | ❌ | Needs real care to avoid presenting an LLM's judgment as definitive fact. Verifying beyond this app's own ingested corpus needs a real search API (Tavily/Serper/etc. -- clean extracted results, not scraping, which was explicitly considered and rejected: inconsistent with this project's RSS-over-scraping principle, legally murky at arbitrary scale, and doesn't fix the underlying reliability problem anyway). Project owner was offered a search-API choice and chose to skip this feature for now rather than add the dependency | deferred by explicit choice, not oversight |

**Why one Groq call instead of three** for #27/#28/#30: they all analyze
the same input (a story's articles) from different angles — one call with
a structured 3-section prompt avoids tripling LLM cost/latency per major
story. See [STORY_INTELLIGENCE.md](STORY_INTELLIGENCE.md).

---

## Phase 6 — Predictive Analytics

| # | Feature | Status | Missing components | Dependencies | Priority |
|---|---|---|---|---|---|
| 32 | Trend prediction | ❌ | No feature engineering, no model, nothing | `scikit-learn` (roadmap's own suggestion; sufficient at this scale) | — |
| 33 | Predictive features | ❌ | Rolling volume/growth/acceleration/diversity/sentiment-change/entity-growth — none computed today, all blocked on #9-11 for their inputs | none new beyond #10/#11's | blocked |
| 34 | Trend momentum score | ❌ | Formula + configurable weights (same pattern as existing `pipeline/scoring.py`) | none new | blocked on #33 |
| 35 | Predictive dashboard | ❌ | UI, blocked on #32-34 | — | blocked |
| 36 | Model evaluation | ❌ | Time-based/walk-forward validation harness | `scikit-learn`'s `TimeSeriesSplit` or hand-rolled walk-forward | blocked on #32 |
| 37 | Model versioning | ❌ | Lightweight approach sufficient (roadmap says don't add MLflow unless justified — nothing here justifies it yet) | none new | blocked on #32 |

**This entire phase has a data-volume blocker independent of code:** the
DB currently holds a few hours of ingestion from this dev session. Time-
based/walk-forward validation needs meaningfully more historical data
(weeks, ideally) to produce a model that's validated rather than just
fitted to a handful of ingestion cycles. Building the feature-engineering
pipeline can start once #9-11 exist; training/evaluating a real model
should wait for the background scheduler to accumulate real history.

---

## Phase 7 — Financial / Market Intelligence

| # | Feature | Status | Missing components | Dependencies | Priority |
|---|---|---|---|---|---|
| 38 | News + market data | ❌ | No market data integration exists in any form | a market data API — `yfinance` (free, no key) is the lowest-friction option; Alpha Vantage/Polygon need keys for more coverage | — |
| 39 | Market sentiment dashboard | ❌ | Blocked on #10 + #38 | — | blocked |
| 40 | Event study | ❌ | Blocked on #38; needs real event-study methodology (pre/post price windows, abnormal/cumulative-abnormal returns) with the roadmap's own required disclaimer that correlation isn't causation | — | blocked |
| 41 | Smart news search | ✅ | Latest Stories tab now has category/sentiment/source/date-range filters, backed by `db.get_stories`'s new filter parameters (filters on each story's *primary* article — see its docstring for why). Natural-language-to-filter conversion ("if feasible" per the roadmap's own hedge) not built — a real LLM-call addition, deferred | done for structured filters; NL conversion deferred |
| 42 | Topic pages | ❌ | Blocked on #9; also needs page-based routing Streamlit doesn't have yet (see Technical Debt in PROJECT_AUDIT.md) | — | blocked |
| 43 | Entity pages | ❌ | Blocked on #11 + routing | — | blocked |
| 44 | Download/export | ✅ | CSV + JSON export on both the Search tab (source articles) and Latest Stories tab (filtered story list) via stdlib `csv`/`json` — no new dependency. Excel/PDF not built (would need `openpyxl`/a PDF library) | done for CSV/JSON; Excel/PDF deferred |

---

## Cross-Cutting Sections

| Section | Status | Notes |
|---|---|---|
| §45 Frontend navigation | 🟡 | Two tabs + sidebar exist; no nav structure for the ~10 new sections the roadmap envisions — would need a real restructure (multi-page Streamlit app or `st.query_params` routing) before Phase 3+ pages make sense |
| §46 Homepage | ❌ | Current "Search" tab isn't a homepage in the roadmap's sense (Top Stories/Trending/etc. sections) |
| §47 Article page | ❌ | No dedicated article page exists; search results render inline |
| §48 Story page | 🟡 | Latest Stories tab's "View articles" expander is a minimal version; no dedicated page with timeline/cross-source/sentiment/etc. |
| §49 Performance | ✅ | Already the existing design: scheduled ingestion + SQLite + `st.cache_data`, precomputed dedup/clustering/scoring at ingestion time, not per-pageview |
| §50 Security | ✅ | Env-var keys, `.env` git-ignored, `.env.example` current, secret-redacting log filter. No user data exists yet to protect (no auth); no validated public input surface yet (single local user) |
| §51 Database | See PROJECT_AUDIT.md | 3 tables exist; the roadmap's ~15-table list is aspirational, not a requirement to build all at once — new tables should land with the feature that needs them |
| §52 Testing | 🟡 | 69 tests cover everything that exists (Phase 1 + clustering/scoring foundations); zero coverage for anything not yet built, by definition |
| §53 Monitoring | ✅ (provider) / ❌ (ML) | Provider status panel already exists in the sidebar (`ProviderRegistry.status_report()`); no ML monitoring exists since no ML exists |
| §54 Documentation | 🟡 | 7 of 14 requested docs already exist (`ARCHITECTURE`, `NEWS_PROVIDERS`≈`PROVIDERS`, `DATA_PIPELINE`≈`NEWS_PIPELINE`, `DEDUPLICATION`, `STORY_CLUSTERING`, plus this audit pair). Missing: `NLP`, `ANALYTICS`, `PREDICTIVE_ANALYTICS`, `MARKET_DATA`, `RAG`, `EXPORTS`, `DEPLOYMENT` — all for unbuilt features |
| §56 Copyright/source rules | ✅ | Already the existing design: no full-article storage, snippets/descriptions only, always links to the original source — documented in `DATA_PIPELINE.md`'s "What we don't store" |

---

## Summary

**Fully built:** Phase 1 (all 7 items) + all of Phase 2 + all of Phase 3
(minus one Source Analytics sub-metric and weekly/monthly rollup
granularity, both noted as deferred, not silently skipped) + 6 of Phase
5's 7 items (story timeline, cross-source comparison, coverage
perspective, why this matters, smart search, export —
#27/#28/#29/#30/#41/#44). This is substantially more than the roadmap's
own checklist assumes as a starting point.

Also built beyond the roadmap's own numbered list: a homepage ("Home" tab
with a hero story + ranked grid), a 2-column story grid replacing the flat
list, category pills, and locally-persisted saved stories (a Phase-4-
adjacent feature that doesn't need the full auth decision, since this is
a single-local-user tool) — all in `docs/STORY_INTELLIGENCE.md` and the
session history.

**Missing, no new hard dependency:** topic/entity/story pages (pending
routing — see PROJECT_AUDIT.md's Technical Debt), natural-language
search-to-filter conversion (#41's "if feasible" stretch goal), Excel/PDF
export (#44's stretch beyond CSV/JSON).

**Missing, needs a real new dependency + design decision:** RAG (#26 —
project owner chose TF-IDF-only retrieval when that phase starts),
predictive analytics (#32-37 — scikit-learn + enough historical data; now
genuinely unblocked, since sentiment/entities/volume — the feature-
engineering inputs — all exist), market data (#38-40 — a market API),
exports beyond CSV/JSON (#44 — openpyxl/PDF library).

**Blocked on a decision only the project owner can make:** Phase 4
(personalization) needs an identity model — the project owner chose a
lightweight per-browser identity (no login) for when that phase starts;
not yet built.
