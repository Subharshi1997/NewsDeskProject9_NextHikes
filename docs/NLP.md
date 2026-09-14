# NLP (Phase 2: Sentiment, Entities, Importance, AI Summaries, Trending)

Everything here runs during **scheduled ingestion** (`pipeline/ingest.py`),
never on a page load — consistent with this project's existing
"precompute, don't call expensive models per request" principle (see
`ARCHITECTURE.md`). The on-demand Search tab does **not** run sentiment,
entity extraction, or story summarization; it only fetches, validates, and
dedupes (see "Why Search stays lightweight" below).

## Sentiment analysis

`pipeline/sentiment.py`. Model:
[`cardiffnlp/twitter-roberta-base-sentiment-latest`](https://huggingface.co/cardiffnlp/twitter-roberta-base-sentiment-latest)
via `transformers.pipeline("sentiment-analysis", ...)` — a real 3-class
(positive/neutral/negative) transformer, per the project owner's explicit
choice over a lighter rule-based approach. Loaded lazily (first real call,
not at import time) and cached as a module-level singleton — loading takes
a few seconds, so it happens once per process, not per article.

`analyze_article_sentiment(article)` runs on `title + description`,
truncated to `MAX_TEXT_LENGTH` (512 chars). Stores `sentiment` (label) and
`sentiment_score` (confidence, 0-1) directly on the `NormalizedArticle`,
persisted to `articles.sentiment`/`articles.sentiment_score`.

**Graceful degradation**: if `transformers`/`torch` aren't installed, the
model fails to download, or classification throws for any reason,
`analyze_sentiment` returns `(None, None)` and logs a warning — it never
raises, so a sentiment-model problem can't take down an ingestion cycle.

**Story-level sentiment** isn't a persisted aggregate — `db.get_story_sentiment(story_id)`
computes counts + average score on demand via SQL `GROUP BY`, so it's
always in sync with the underlying article rows rather than needing to be
kept in sync by hand.

## Entity extraction

`pipeline/entities.py`. Model: spaCy's `en_core_web_sm`, per the project
owner's explicit choice over skipping this feature. Same lazy-load/
graceful-degradation pattern as sentiment.

Extracts `PERSON`, `ORG`, `GPE`, `LOC`, `PRODUCT`, `NORP`, `MONEY` labels
(spaCy's own taxonomy) from `title + description`, deduplicated per
article by (lowercase text, label). **Known limitations, by design, not
oversights:**

- spaCy doesn't distinguish "company" from other organization types, or
  "country" from city/state (`GPE` covers both) — a real taxonomy would
  need a second classification pass.
- "Stocks" (ticker symbols) aren't a spaCy label at all and aren't
  extracted here — resolving a company mention to a ticker is Phase 7
  (Market Intelligence) territory, not Phase 2.
- No cross-article entity resolution/linking: "Nvidia" and "NVIDIA Corp"
  are stored as two distinct entities. Real entity linking is a
  meaningfully harder NLP problem, out of scope for this pass.
- Off-the-shelf NER has real noise — e.g. short acronyms like "AI"
  sometimes get mistagged as `ORG` or `GPE` depending on context. Observed
  in live ingestion, not hand-patched away (that's whack-a-mole); treat
  entity data as a useful signal, not ground truth.

Persisted via two new tables (`entities`, `article_entities` — see
`db.py`'s schema comment for why this one genuinely is a many-to-many
junction table, unlike story/article).

## Importance score (extends the existing article quality score)

This project's pre-existing `pipeline.scoring.score_article` /
`quality_score` already occupied the same architectural slot as the
roadmap's "Importance Score" (source quality + recency + completeness +
originality) — extended in place rather than creating a second parallel
score:

```
quality_score =
    source * 0.30 + recency * 0.25 + completeness * 0.15 + originality * 0.10
    + source_diversity * 0.15 + entity_importance * 0.05
```

Two new components:
- **`source_diversity_score(story_articles)`** — how many distinct
  *publications* (not API providers) cover this story, normalized,
  capped at 5. A proxy for how significant/corroborated a story is.
- **`entity_importance_score(article)`** — how many distinct named
  entities the article mentions, normalized, capped at 5. A crude
  substance/newsworthiness proxy, **not** a true corpus-wide
  entity-prominence signal (that would need looking up each entity's
  overall `entities.mention_count`, which would couple `pipeline/scoring.py`
  to the database — deliberately avoided to keep that module a pure,
  DB-free, independently testable function set). A natural v2 enhancement
  once there's more ingestion history to make that signal meaningful.

Weights (`DEFAULT_WEIGHTS`) are a parameter on every scoring call, not a
hardcoded constant — override per-call to experiment.

## AI summaries (per-story, cached)

`langchain_config.generate_story_summary` (new chain, reuses the existing
Groq `llm`) — one overview sentence + 3-5 bullet points, explicitly
instructed not to editorialize or speculate beyond what the source
articles state.

**Called only for stories with 2+ articles** (`pipeline.ingest.MIN_ARTICLES_FOR_SUMMARY`)
— a single-article "story" doesn't need cross-source synthesis, and this
keeps LLM calls per ingestion cycle proportional to "stories actually
worth summarizing" rather than raw article count (most stories in a batch
are single-article). **Generated once, cached forever**: `pipeline.ingest._generate_story_summaries`
checks `db.get_story(story_id)` for an existing non-empty `summary` before
calling Groq, and `db.ensure_story`'s `summary` parameter is only written
when the caller explicitly generated a fresh one — an existing cached
summary is never clobbered with `NULL` on a later cycle that didn't
regenerate it.

## Trending topics

`pipeline/trending.py`. **Not raw article-volume ranking** — a transparent
weighted score:

```
trending_score =
    growth * 0.4 + volume * 0.2 + recency * 0.2 + diversity * 0.2
```

- **growth**: this window's article volume vs. the prior equal-length
  window, capped at 300% to avoid noisy 0→1 jumps dominating the ranking.
- **volume**: absolute in-window count, capped at 20.
- **recency**: exponential decay, 6-hour half-life (sharper than article
  scoring's 12-hour half-life — trending should reward very fresh activity
  more aggressively).
- **diversity**: distinct source count in-window, capped at 5.

Supports `24h`/`7d`/`30d` windows (`pipeline.trending.WINDOWS`).

**Design choice: topics = extracted entities, not topic modeling.**
Trending here operates over the `entities`/`article_entities` tables built
by entity extraction above, not a separate LDA/BERTopic-style topic model
— a deliberate simplification consistent with "avoid unnecessary
dependencies." Consequence: a conceptual/thematic phrase like "AI
Regulation" (from the roadmap's own example) won't surface as its own
trending item unless it also happens to be tagged as a named entity;
"Nvidia" or "RBI" will, since those are real entities. Category-level
trending (business/technology/...) is a natural, cheap follow-up — `db.get_articles`
already supports category filtering — but wasn't built in this pass to
keep this module's scope contained.

## Why Search stays lightweight

The on-demand Search tab (`langchain_config.get_news_articles`) does
**not** run sentiment, entities, or story summarization — only fetch,
validate, dedupe. Running two ML models (sentiment + NER) plus an LLM call
synchronously on every interactive search would add real latency (cold
model load alone took ~15-20s in testing) on top of the existing Groq
summarization call, degrading the interactive UX for no benefit — none of
that enrichment is used by the Search tab's output. It's confined to the
background-ingested "Latest Stories"/"Trending" data, which is exactly the
precompute-not-per-request pattern this project has used from the start.

## New dependencies

```
transformers>=4.44.0
spacy>=3.7.0
torch (CPU wheel -- install via https://download.pytorch.org/whl/cpu, see requirements.txt)
```

Plus spaCy's English model (`python -m spacy download en_core_web_sm`),
which isn't a normal pip package. Both are lazy-loaded, so importing
`pipeline.sentiment`/`pipeline.entities` (e.g. in tests) doesn't require
them to be installed or working — only actually calling
`analyze_sentiment`/`extract_entities` does.

## Testing

`tests/test_sentiment.py`, `tests/test_entities.py`, `tests/test_trending.py`,
plus additions to `tests/test_scoring.py` (diversity/entity-importance) and
`tests/test_db.py` (entity persistence, story summaries, sentiment
aggregation) — all mock the underlying models (`_get_classifier`/`_get_nlp`),
so the test suite stays fast and doesn't need `torch`/`spacy`'s models
downloaded to run. Live end-to-end validation (real models, real Groq
calls, real ingestion data) was run separately and is summarized in
`FEATURE_ROADMAP_STATUS.md`.
