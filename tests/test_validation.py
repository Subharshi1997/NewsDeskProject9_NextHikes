from datetime import datetime, timedelta, timezone

from pipeline.validation import clean_published_at, is_valid_url, validate_article, validate_articles
from providers.base import NormalizedArticle


def make_article(**overrides):
    defaults = dict(article_id="1", title="A valid title", url="https://example.com/a", provider="p", source_name="Source")
    defaults.update(overrides)
    return NormalizedArticle(**defaults)


def test_is_valid_url():
    assert is_valid_url("https://example.com/a") is True
    assert is_valid_url("http://example.com/a") is True
    assert is_valid_url("not-a-url") is False
    assert is_valid_url("") is False
    assert is_valid_url(None) is False
    assert is_valid_url("ftp://example.com/a") is False


def test_validate_article_rejects_missing_title():
    article = make_article(title="")
    ok, reasons = validate_article(article)
    assert ok is False
    assert "title missing or too short" in reasons


def test_validate_article_rejects_too_short_title():
    article = make_article(title="Hi")
    ok, reasons = validate_article(article)
    assert ok is False


def test_validate_article_rejects_invalid_url():
    article = make_article(url="not-a-url")
    ok, reasons = validate_article(article)
    assert ok is False
    assert "url missing or invalid" in reasons


def test_validate_article_rejects_missing_source():
    article = make_article(source_name="")
    ok, reasons = validate_article(article)
    assert ok is False
    assert "source missing" in reasons


def test_validate_article_accepts_well_formed_article():
    article = make_article()
    ok, reasons = validate_article(article)
    assert ok is True
    assert reasons == []


def test_clean_published_at_clears_impossible_future_date():
    now = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
    article = make_article(published_at=(now + timedelta(days=365)).isoformat())
    clean_published_at(article, now=now)
    assert article.published_at is None


def test_clean_published_at_keeps_reasonable_date():
    now = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
    original = (now - timedelta(hours=2)).isoformat()
    article = make_article(published_at=original)
    clean_published_at(article, now=now)
    assert article.published_at == original


def test_clean_published_at_clears_unparseable_date():
    article = make_article(published_at="not-a-date")
    clean_published_at(article)
    assert article.published_at is None


def test_validate_articles_filters_and_keeps_valid_ones():
    good = make_article(title="A perfectly good title", url="https://example.com/1")
    bad = make_article(title="", url="https://example.com/2", article_id="2")
    result = validate_articles([good, bad])
    assert result == [good]
