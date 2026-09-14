import hashlib
import logging
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import numpy as np

logger = logging.getLogger("news_research_tool.pipeline.dedup")

# Tracking params stripped during URL canonicalization (Level 1).
TRACKING_PARAM_PREFIXES = ("utm_",)
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "mc_cid", "mc_eid", "ref", "ref_src", "igshid",
    "spm", "cmpid", "cmp", "ito", "smid",
}

DEFAULT_SEMANTIC_THRESHOLD = 0.82


def canonicalize_url(url):
    """Level 1: normalize a URL for equality comparison — lowercase
    scheme/host, drop 'www.', strip tracking params, drop fragment/trailing
    slash, sort remaining query params.
    """
    if not url:
        return ""
    parts = urlsplit(url.strip())
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parts.path.rstrip("/") or ""
    kept_params = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith(TRACKING_PARAM_PREFIXES)
    )
    return urlunsplit(("https", netloc, path, urlencode(kept_params), ""))


def normalize_title(title):
    """Level 2: lowercase, strip punctuation, collapse whitespace."""
    if not title:
        return ""
    title = title.lower()
    title = re.sub(r"[^\w\s]", "", title)
    return re.sub(r"\s+", " ", title).strip()


def content_hash(title):
    """Stable hash of a normalized title, used for Level-2 exact-match dedup."""
    return hashlib.sha256(normalize_title(title).encode("utf-8")).hexdigest()


def _tokenize(text):
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def tfidf_vectors(texts):
    """Minimal TF-IDF over a list of texts using only numpy + stdlib —
    deliberately not scikit-learn, to avoid a heavy ML dependency for a
    project this size. Returns an (n_docs, vocab_size) numpy array.
    """
    tokenized = [_tokenize(t) for t in texts]
    vocab = {}
    for tokens in tokenized:
        for tok in set(tokens):
            vocab.setdefault(tok, len(vocab))

    n_docs, n_vocab = len(texts), len(vocab)
    if n_vocab == 0:
        return np.zeros((n_docs, 0))

    tf = np.zeros((n_docs, n_vocab))
    for i, tokens in enumerate(tokenized):
        for tok in tokens:
            tf[i, vocab[tok]] += 1
        if tokens:
            tf[i] /= len(tokens)

    df = np.count_nonzero(tf > 0, axis=0)
    idf = np.log((1 + n_docs) / (1 + df)) + 1
    return tf * idf


def cosine_similarity(vec_a, vec_b):
    norm_a, norm_b = np.linalg.norm(vec_a), np.linalg.norm(vec_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))


def cosine_similarity_matrix(vectors):
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1e-9
    normalized = vectors / norms
    return normalized @ normalized.T


def deduplicate(articles, semantic_threshold=DEFAULT_SEMANTIC_THRESHOLD):
    """Run all 3 dedup levels over a list of NormalizedArticle, in place.

    Sets canonical_url/content_hash/is_duplicate on every article. Does
    NOT remove anything from the input list — callers decide whether to
    filter on is_duplicate (the ingestion pipeline keeps duplicates in the
    DB, flagged, rather than discarding data; the on-demand search path
    filters them out before summarizing).
    """
    seen_urls, seen_hashes = set(), set()
    stage1_survivors = []

    for article in articles:
        article.canonical_url = canonicalize_url(article.url)
        article.content_hash = content_hash(article.title)
        article.is_duplicate = False

        if article.canonical_url and article.canonical_url in seen_urls:
            article.is_duplicate = True
            continue
        if article.content_hash and article.content_hash in seen_hashes:
            article.is_duplicate = True
            continue

        seen_urls.add(article.canonical_url)
        seen_hashes.add(article.content_hash)
        stage1_survivors.append(article)

    _semantic_dedup(stage1_survivors, semantic_threshold)

    removed = sum(1 for a in articles if a.is_duplicate)
    logger.info("dedup: %d/%d articles flagged as duplicates", removed, len(articles))
    return articles


def _semantic_dedup(candidates, threshold):
    if len(candidates) < 2:
        return
    texts = [f"{a.title} {a.description or ''}" for a in candidates]
    vectors = tfidf_vectors(texts)
    if vectors.shape[1] == 0:
        return

    survivor_indices = []
    for i, article in enumerate(candidates):
        is_dup = any(
            cosine_similarity(vectors[i], vectors[j]) >= threshold
            for j in survivor_indices
        )
        if is_dup:
            article.is_duplicate = True
        else:
            survivor_indices.append(i)
