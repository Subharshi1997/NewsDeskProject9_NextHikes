# Analytics (Phase 3)

A new "📊 Analytics" tab in `app.py`, with five sub-sections (a radio
selector, not five separate top-level tabs, per "do not overcrowd the
page"). All data comes from `db.py`'s aggregation queries + `analytics.py`'s
derived calculations — nothing here calls an external API or a model; it's
read-only aggregation over what background ingestion has already stored.

## Overview (roadmap #14)

- **Articles Today / This Week / This Month** — `analytics.volume_summary()`.
- **News Volume Over Time** (30-day area chart) — `db.get_volume_by_day`.
- **Top Categories** / **Top Sources** (bar charts) — `db.get_top_categories`
  / `db.get_top_sources`.

## Sentiment Trends (roadmap #15)

Daily positive/neutral/negative counts (`db.get_sentiment_trend_by_day`),
pivoted into a 3-line chart. Depends entirely on Phase 2's sentiment
scoring — there's no separate sentiment computation here.

## Source Analytics (roadmap #16)

A sortable table (`db.get_top_sources`): articles published, average
importance (the `quality_score` from `pipeline/scoring.py`), average
sentiment score, and distinct story coverage count, for every source seen.
Streamlit's native dataframe sorting/filtering stands in for "source
comparisons" — no bespoke comparison UI was built on top of it.

**Not implemented from the roadmap's #16 list**: "Trending Coverage" (how
much of a source's output is currently trending) — would need cross-
referencing `pipeline.trending`'s output against each source's articles'
entities, a heavier join not built in this pass.

## Topic Analytics (roadmap #17)

Pick an entity from a dropdown (`db.get_top_entities`), see
`analytics.entity_analytics(entity_name)`: 24h volume + growth vs. the
prior 24h, source diversity, dominant sentiment tone, top sources covering
it, and a historical daily-volume bar chart. Same "topics = extracted
entities, not topic modeling" design choice as `pipeline/trending.py` —
see [NLP.md](NLP.md) for why, and what that means you won't see here (a
thematic phrase like "AI Regulation" won't appear unless it's also a named
entity).

## Country Heatmap (roadmap #18)

A Plotly choropleth (`px.choropleth`, `locationmode="ISO-3"`) over
`analytics.country_volume(days=...)`, with a 24h/7d/30d window selector.

**This one needed real data cleanup, not just a chart.** The `country`
field as stored is genuinely messy:

```
'IN'                                    -- NewsData.io / RSS config, 2-letter code
'united states of america'              -- NewsData.io, lowercase full name
'china, romania, singapore, ... (27 more)'  -- one NewsData.io article tagged
                                            with dozens of countries at once
```

`analytics.normalize_country_field(raw)` splits comma-separated values and
resolves each piece to an ISO-3 code + display name via `pycountry`
(exact alpha-2/alpha-3 lookup first, then a small supplementary alias
table for common near-misses like "ivory coast" that `pycountry`'s fuzzy
search doesn't resolve, then fuzzy name search as a last resort).
**Unrecognized pieces are silently dropped, not guessed at** — a genuine
upstream data typo observed live (`"burkina fasco"`, one character off
from "Burkina Faso") is left unresolved rather than pattern-matched away.
This means country coverage on the map is a best-effort subset, not
exhaustive — stated explicitly in the UI, not hidden.

The same multi-value-field problem existed in the `category` field
(`db.get_top_categories` — see its docstring) and got the same treatment:
split and re-aggregated in Python rather than grouped raw in SQL, so a
compound value like `"top, politics"` contributes to both real categories
instead of forming its own bogus bucket.

## Historical Analysis (roadmap #19)

Not a separate section — folded into Overview's volume chart (30-day daily
granularity) and Topic Analytics' per-entity historical volume, rather
than a sixth UI section. Weekly/monthly rollups are a small extension of
`db.get_volume_by_day` (bucket by week/month instead of day) if needed
later, not built now to avoid a section that would mostly duplicate
Overview's chart.

## New dependencies

```
pycountry>=23.12.0   # country name/code normalization -- a data-lookup
                      # library, not a model; no meaningful runtime weight
plotly>=5.20.0        # the one chart type (choropleth) Streamlit's
                       # built-in charts don't support
```

Everything else (line/bar/area charts, dataframes) uses Streamlit's native
chart functions (backed by Altair, already a Streamlit dependency) — no
new dependency needed for those.

## Testing

`tests/test_analytics.py` (country normalization, volume summary, entity
analytics — all mocking `db.*` calls) and additions to `tests/test_db.py`
(every new aggregation query, including the category/country
multi-value-splitting behavior specifically). All isolated/fast, no
network or model calls.
