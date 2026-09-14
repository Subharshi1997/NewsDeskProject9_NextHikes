from unittest.mock import Mock, patch

import pipeline.sentiment as sentiment
from providers.base import NormalizedArticle


def make_article(**overrides):
    defaults = dict(article_id="1", title="Title", url="https://example.com/a", provider="p", source_name="Source")
    defaults.update(overrides)
    return NormalizedArticle(**defaults)


def test_analyze_sentiment_returns_label_and_rounded_score():
    fake_classifier = Mock(return_value=[{"label": "positive", "score": 0.876543}])
    with patch.object(sentiment, "_get_classifier", return_value=fake_classifier):
        label, score = sentiment.analyze_sentiment("Great news for the company.")
    assert label == "positive"
    assert score == 0.8765


def test_analyze_sentiment_empty_text_skips_the_model():
    fake_classifier = Mock()
    with patch.object(sentiment, "_get_classifier", return_value=fake_classifier):
        result = sentiment.analyze_sentiment("")
    assert result == (None, None)
    fake_classifier.assert_not_called()


def test_analyze_sentiment_none_text_skips_the_model():
    fake_classifier = Mock()
    with patch.object(sentiment, "_get_classifier", return_value=fake_classifier):
        result = sentiment.analyze_sentiment(None)
    assert result == (None, None)
    fake_classifier.assert_not_called()


def test_analyze_sentiment_returns_none_when_model_unavailable():
    with patch.object(sentiment, "_get_classifier", return_value=None):
        result = sentiment.analyze_sentiment("Some text.")
    assert result == (None, None)


def test_analyze_sentiment_handles_classifier_exception_gracefully():
    fake_classifier = Mock(side_effect=RuntimeError("boom"))
    with patch.object(sentiment, "_get_classifier", return_value=fake_classifier):
        result = sentiment.analyze_sentiment("Some text.")
    assert result == (None, None)


def test_analyze_sentiment_truncates_long_text():
    fake_classifier = Mock(return_value=[{"label": "neutral", "score": 0.5}])
    long_text = "x" * 1000
    with patch.object(sentiment, "_get_classifier", return_value=fake_classifier):
        sentiment.analyze_sentiment(long_text)
    called_text = fake_classifier.call_args[0][0]
    assert len(called_text) == sentiment.MAX_TEXT_LENGTH


def test_analyze_article_sentiment_combines_title_and_description():
    fake_classifier = Mock(return_value=[{"label": "neutral", "score": 0.5}])
    article = make_article(title="Nvidia earnings", description="Beat expectations")
    with patch.object(sentiment, "_get_classifier", return_value=fake_classifier):
        sentiment.analyze_article_sentiment(article)
    called_text = fake_classifier.call_args[0][0]
    assert "Nvidia earnings" in called_text
    assert "Beat expectations" in called_text
