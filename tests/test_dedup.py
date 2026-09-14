import pytest

from pipeline.dedup import canonicalize_url, content_hash, cosine_similarity, deduplicate, normalize_title, tfidf_vectors
from providers.base import NormalizedArticle


def make_article(**overrides):
    defaults = dict(article_id="1", title="Title", url="https://example.com/a", provider="p", source_name="Source")
    defaults.update(overrides)
    return NormalizedArticle(**defaults)


def test_canonicalize_url_strips_tracking_params_and_www():
    a = canonicalize_url("https://WWW.Example.com/story/?utm_source=twitter&utm_medium=social&id=42")
    b = canonicalize_url("https://example.com/story?id=42")
    assert a == b


def test_canonicalize_url_strips_trailing_slash_and_fragment():
    a = canonicalize_url("https://example.com/story/#section")
    b = canonicalize_url("https://example.com/story")
    assert a == b


def test_normalize_title_lowercases_and_strips_punctuation():
    assert normalize_title("Nvidia's Earnings: A Big Beat!") == "nvidias earnings a big beat"


def test_content_hash_matches_for_equivalent_titles():
    assert content_hash("Nvidia's Earnings!") == content_hash("nvidias earnings")


def test_deduplicate_flags_same_url_from_different_providers():
    a1 = make_article(title="Story A", url="https://example.com/story?utm_source=fb", provider="newsdata")
    a2 = make_article(title="Story A (different casing)", url="https://example.com/story", provider="rss")
    deduplicate([a1, a2])
    assert a1.is_duplicate is False
    assert a2.is_duplicate is True


def test_deduplicate_flags_same_normalized_title_different_url():
    a1 = make_article(title="Nvidia beats earnings expectations", url="https://a.example.com/1")
    a2 = make_article(title="Nvidia Beats Earnings Expectations!", url="https://b.example.com/2")
    deduplicate([a1, a2])
    assert a1.is_duplicate is False
    assert a2.is_duplicate is True


def test_deduplicate_flags_semantically_similar_titles():
    a1 = make_article(
        title="Nvidia posts record quarterly revenue on AI chip demand",
        description="Nvidia reported record revenue driven by strong AI chip demand this quarter.",
        url="https://a.example.com/1",
    )
    a2 = make_article(
        title="Nvidia reports record quarterly revenue amid AI chip demand",
        description="Nvidia reported record revenue driven by strong AI chip demand this quarter, up sharply.",
        url="https://b.example.com/2",
    )
    deduplicate([a1, a2], semantic_threshold=0.6)
    assert a1.is_duplicate is False
    assert a2.is_duplicate is True


def test_deduplicate_keeps_distinct_articles():
    a1 = make_article(title="Nvidia earnings beat expectations", url="https://a.example.com/1")
    a2 = make_article(title="Federal Reserve holds interest rates steady", url="https://b.example.com/2")
    deduplicate([a1, a2])
    assert a1.is_duplicate is False
    assert a2.is_duplicate is False


def test_cosine_similarity_identical_vectors_is_one():
    vectors = tfidf_vectors(["nvidia earnings beat", "nvidia earnings beat"])
    sim = cosine_similarity(vectors[0], vectors[1])
    assert sim == pytest.approx(1.0, abs=1e-6)


def test_cosine_similarity_unrelated_texts_is_low():
    vectors = tfidf_vectors(["nvidia earnings beat expectations", "cricket world cup final result"])
    sim = cosine_similarity(vectors[0], vectors[1])
    assert sim < 0.3
