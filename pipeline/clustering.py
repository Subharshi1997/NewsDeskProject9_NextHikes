import hashlib
import logging

from .dedup import cosine_similarity, tfidf_vectors

logger = logging.getLogger("news_research_tool.pipeline.clustering")

# Lower than the dedup threshold on purpose: story-mates are different
# articles (different wording, different outlets) covering the same event,
# not near-identical copies of the same text.
DEFAULT_CLUSTER_THRESHOLD = 0.35


def _make_story_id(title, url):
    basis = f"{title}|{url}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def cluster_stories(articles, threshold=DEFAULT_CLUSTER_THRESHOLD):
    """Group articles covering the same underlying story via greedy
    single-link TF-IDF cosine clustering over title+description text.

    Only considers non-duplicate articles — exact/near duplicates were
    already resolved by pipeline.dedup.deduplicate(). Mutates story_id on
    each article and returns {story_id: [articles]}.

    Deliberately simple (TF-IDF, greedy single-link) so the similarity
    function can be swapped for sentence embeddings later without changing
    the clustering logic around it.
    """
    candidates = [a for a in articles if not a.is_duplicate]
    if not candidates:
        return {}

    texts = [f"{a.title} {a.description or ''}" for a in candidates]
    vectors = tfidf_vectors(texts)

    clusters = []
    for i in range(len(candidates)):
        placed = False
        if vectors.shape[1] > 0:
            for cluster in clusters:
                seed_idx = cluster[0]
                if cosine_similarity(vectors[i], vectors[seed_idx]) >= threshold:
                    cluster.append(i)
                    placed = True
                    break
        if not placed:
            clusters.append([i])

    story_map = {}
    for cluster in clusters:
        seed = candidates[cluster[0]]
        story_id = _make_story_id(seed.title, seed.canonical_url or seed.url)
        story_articles = []
        for idx in cluster:
            article = candidates[idx]
            article.story_id = story_id
            story_articles.append(article)
        story_map[story_id] = story_articles

    logger.info("clustering: grouped %d articles into %d stories", len(candidates), len(story_map))
    return story_map
