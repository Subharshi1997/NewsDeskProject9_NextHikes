# Deduplication

`pipeline/dedup.py`. Runs once per ingestion batch (a search's combined
results, or one scheduled ingest cycle), in three levels, cheapest first --
each level only compares articles the previous level didn't already flag.

## Level 1 -- URL

`canonicalize_url(url)`:

- forces `https` scheme,
- lowercases the host, strips a leading `www.`,
- strips a trailing slash and the fragment (`#...`),
- drops known tracking params (`utm_*`, `gclid`, `fbclid`, `ref`,
  `ref_src`, `igshid`, `mc_cid`/`mc_eid`, `spm`, `cmp`/`cmpid`, `ito`,
  `smid`) and sorts whatever query params remain, so param order doesn't
  matter.

Two articles whose canonical URLs match are the same article -- the first
one seen is kept, the rest flagged `is_duplicate`.

```python
canonicalize_url("https://WWW.Example.com/story/?utm_source=x&id=42")
# -> "https://example.com/story?id=42"
```

## Level 2 -- exact title match

`normalize_title(title)` lowercases, strips punctuation, and collapses
whitespace; `content_hash(title)` is `sha256` of that normalized string.
Catches the same article syndicated under a different URL (e.g. a wire
story mirrored by two outlets) whose title text is otherwise identical.

## Level 3 -- semantic similarity

Hand-rolled TF-IDF (`tfidf_vectors`) + cosine similarity
(`cosine_similarity`), using only `numpy` -- deliberately not
scikit-learn/embeddings, to avoid a heavy ML dependency at this project's
scale (see [ARCHITECTURE.md](ARCHITECTURE.md) for the reasoning). Runs over
`title + " " + description` for whatever survived Levels 1/2, greedily: a
new article is flagged as a duplicate of the first already-kept article its
similarity exceeds `DEFAULT_SEMANTIC_THRESHOLD = 0.82`.

0.82 is deliberately high -- this level exists to catch near-identical
copies (the same wire report with a word or two changed), not "articles
about the same event," which is what clustering (a much lower 0.35
threshold) is for instead. See [STORY_CLUSTERING.md](STORY_CLUSTERING.md).

## Defense in depth at the DB layer

`db.py`'s `articles` table has `UNIQUE(canonical_url)`. `insert_article`
catches the resulting `sqlite3.IntegrityError` and reports "not inserted"
rather than raising -- so even if a caller skipped `pipeline.dedup` for
some article, the same canonical URL still can't end up as two rows.

## What gets stored

Duplicates are **not** persisted at all (not even flagged-but-kept) --
`db.store_articles` skips any article with `is_duplicate=True` before ever
calling `insert_article`. "Don't store four copies" is enforced by not
writing the rows in the first place, not by a query-time filter.

## Testing

`tests/test_dedup.py` covers all three levels independently (tracking
params, trailing slash/fragment, punctuation-only title differences,
near-identical titles+descriptions, and that genuinely distinct articles
survive).
