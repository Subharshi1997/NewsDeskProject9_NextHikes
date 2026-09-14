# Data Pipeline

## Normalized article schema

`providers.base.NormalizedArticle`:

```
article_id     provider's native id, or its url as a fallback
title          required
url            required
provider       "newsdata" | "rss" | ...
source_name    e.g. "cnbc" (NewsData.io) or "BBC News" (RSS config's "name")
description    optional
content        optional -- often None; see "What we don't store" below
image_url      optional
source_url     optional (the feed/publisher homepage, for RSS)
author         optional
published_at   ISO 8601 string, or None
fetched_at     ISO 8601 string, set by the provider at fetch time
language       optional
country        optional
category       optional
keywords       list, defaults to []

# filled in by the pipeline, not by providers:
canonical_url  set by pipeline.dedup
content_hash   set by pipeline.dedup
story_id       set by pipeline.clustering
quality_score  set by pipeline.scoring
is_duplicate   set by pipeline.dedup
is_primary     set by pipeline.scoring.select_primary
```

Every provider's `_normalize()` method is responsible for mapping its raw
response onto this shape -- see `NewsDataProvider._normalize` and
`RSSProvider._normalize` for the two current examples.

## What we don't store

Per Rule 10 (no full copyrighted article bodies): `content` is left `None`
whenever a provider doesn't hand back genuinely free content --
`NewsDataProvider` explicitly discards Newsdata's `"ONLY AVAILABLE IN PAID
PLANS"` placeholder rather than storing it as if it were real text.
`RSSProvider` never populates `content` at all -- an RSS `<summary>` is a
snippet, not the article body, and that's what `description` is for. Every
stored article carries `url` back to the original publisher.

## Pipeline stages (scheduled ingestion: `pipeline/ingest.py`)

```
providers.registry.fetch_all()      # fetch, per-provider retry/backoff/failover
        v
pipeline.validation.validate_articles()   # drop unusable, clear impossible dates
        v
pipeline.dedup.deduplicate()        # Level 1/2/3, see DEDUPLICATION.md
        v
pipeline.clustering.cluster_stories()     # see STORY_CLUSTERING.md
        v
pipeline.scoring.select_primary()   # per story: score every article, pick the best
        v
db.store_articles()                 # non-duplicates only; sources/stories upserted first (FK order)
```

The on-demand search path (`langchain_config.get_news_articles`) runs a
shorter version of the same pipeline -- fetch, validate, dedup -- and skips
clustering/scoring/storage, since a single search's results are summarized
by the LLM immediately rather than browsed later.

## Data quality rules (section 20)

Implemented in `pipeline/validation.py`. An article is **rejected**
(dropped entirely) if:

- its title is missing or under 5 characters (title drives dedup,
  clustering, and display -- unusable without one),
- its URL doesn't parse as an absolute `http(s)` URL (Rule 10 depends on a
  working link back to the source),
- its source name is missing (breaks the `sources` FK and scoring; in
  practice both current providers already backfill `"Unknown"`, so this is
  a defensive backstop more than something live traffic hits).

An article's publication date is **cleared, not rejected**, if it's more
than 48 hours in the future (allows for timezone/clock skew across
providers) -- the rest of the article is still usable, and a cleared date
just falls back to `scoring.recency_score()`'s existing 0.0-for-missing
behavior.

"Clearly duplicate" (also listed in section 20) is deliberately not
validation's job -- that's `pipeline.dedup`, run immediately after
validation so garbage doesn't get compared against.

## Source quality (section 9)

`config/sources.json`:

```json
{
  "default_quality_score": 2,
  "sources": [
    {"source_name": "Reuters", "quality_score": 5},
    ...
  ]
}
```

`pipeline.scoring.SourceScorer.score(source_name)` does a case-insensitive
exact match first, then a substring fuzzy match (so `"BBC News"` matches a
`"BBC"` entry), then falls back to `default_quality_score`. This is the
*only* source-quality table -- it's consulted for every provider, not just
RSS (RSS sources also carry their own `quality_score` in
`config/rss_sources.json`, used at ingestion time when the article is
known to have come from that exact configured feed).

## Article quality score (section 10)

`pipeline.scoring.score_article`:

```
article_score = source*0.4 + recency*0.3 + completeness*0.2 + originality*0.1
```

All four components are normalized to `[0, 1]` before weighting:

- **source**: `SourceScorer` result (1-5) / 5.
- **recency**: `0.5 ** (age_hours / 12)` -- halves every 12 hours, 0 if the
  date is missing/unparseable.
- **completeness**: fraction of `{description, content, image_url, author}`
  that's populated.
- **originality**: 1.0 for the earliest-published article in its story
  cluster, decaying toward 0.1 for later arrivals; 0.5 if publish times
  in the cluster are missing/unrankable.

Weights live in `pipeline.scoring.DEFAULT_WEIGHTS` and are a parameter on
every scoring function (`score_article`, `select_primary`) -- override them
per-call rather than editing the module if you want to experiment; the
defaults favor source reputation heaviest, since this app has no
reader-engagement data to inform a real "relevance" signal.

## Selecting a story's primary article (section 11)

`pipeline.scoring.select_primary(story_articles)` scores every article in a
cluster and marks the single highest-scoring one `is_primary=True`. The
"Latest Stories" tab and `db.get_story_articles` both surface the primary
article first (marked with a star) -- the frontend never just shows
whichever provider happened to respond first.
