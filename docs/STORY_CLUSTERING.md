# Story Clustering

`pipeline/clustering.py`. Groups *distinct* articles (different wording,
different outlets) that cover the same underlying event -- as opposed to
[deduplication](DEDUPLICATION.md), which collapses near-identical copies of
the *same* article. Clustering runs after dedup and only considers
articles that survived it (`is_duplicate=False`).

## Algorithm

Greedy single-link clustering over the same TF-IDF representation
`pipeline.dedup` uses (`tfidf_vectors` + `cosine_similarity`), at a much
lower threshold than dedup's:

```python
DEFAULT_CLUSTER_THRESHOLD = 0.35   # vs. dedup's 0.82
```

For each candidate article, in order: compare it against the *seed*
(first) article of every existing cluster; join the first cluster whose
seed it's similar enough to, or start a new one if none match. This is
`O(n * k)` where `k` is the current cluster count, which is fine at this
project's per-ingestion-batch scale (tens of articles).

```
India announces new semiconductor policy         (seed)
  + "Government unveils semiconductor manufacturing policy"   (Reuters)
  + "Cabinet approves new chip manufacturing policy"          (The Hindu)

Local team wins regional cricket tournament       (unrelated -> own cluster)
```

## story_id

`hashlib.sha256(f"{seed.title}|{seed.canonical_url or seed.url}")[:16]` --
deterministic from the cluster's first article, so re-running ingestion
against overlapping data tends to produce the same `story_id` for the same
story rather than a fresh random one each cycle.

## Why not a many-to-many `article_story` table

Every article ends up in exactly one cluster by construction (clustering
partitions the input, it doesn't produce overlapping groups) -- so
`articles.story_id` as a plain foreign key is sufficient. See
[db.py](../db.py)'s schema comment for the same reasoning applied to the
database design.

## Picking the story's headline article

Clustering only groups articles; it doesn't rank them. That's
`pipeline.scoring.select_primary(story_articles)` (see
[DATA_PIPELINE.md](DATA_PIPELINE.md) section 11), called once per cluster
right after `cluster_stories()` returns, in `pipeline/ingest.py`.

## Swapping in embeddings later

The threshold and the article-to-article comparison are the only two
things that would change: replace `pipeline.dedup.tfidf_vectors` +
`cosine_similarity` with an embedding model's vectors and the same cosine
comparison, and re-tune `DEFAULT_CLUSTER_THRESHOLD` for the new
similarity distribution (embedding cosine similarities aren't on the same
scale as TF-IDF's). `cluster_stories`'s control flow (seed comparison,
greedy assignment, `story_id` generation) doesn't need to change.

## Testing

`tests/test_clustering.py` covers: related articles from different sources
clustering together, unrelated articles staying separate, duplicates
(pre-flagged by dedup) being excluded from clustering entirely, and empty
input.
