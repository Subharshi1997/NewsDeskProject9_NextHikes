import logging

logger = logging.getLogger("news_research_tool.pipeline.sentiment")

MODEL_NAME = "cardiffnlp/twitter-roberta-base-sentiment-latest"
MAX_TEXT_LENGTH = 512  # truncate long text; this model's practical input cap

_classifier = None
_load_failed = False


def _get_classifier():
    """Lazily loads the transformer pipeline on first real use, not at
    import time -- keeps `import pipeline.sentiment` cheap for anything
    that doesn't actually classify text (e.g. most tests).
    """
    global _classifier, _load_failed
    if _classifier is not None or _load_failed:
        return _classifier
    try:
        from transformers import pipeline
        _classifier = pipeline("sentiment-analysis", model=MODEL_NAME)
    except Exception:
        logger.exception(
            "sentiment: failed to load model %r -- sentiment scoring will be skipped for this process",
            MODEL_NAME,
        )
        _load_failed = True
    return _classifier


def analyze_sentiment(text):
    """Returns (label, score): label is 'positive'/'neutral'/'negative',
    score is the model's confidence in [0, 1]. Returns (None, None) for
    empty text or if the model couldn't be loaded -- sentiment is an
    enrichment, never a reason to fail ingestion.
    """
    if not text or not text.strip():
        return None, None
    classifier = _get_classifier()
    if classifier is None:
        return None, None
    try:
        result = classifier(text[:MAX_TEXT_LENGTH])[0]
        return result["label"], round(float(result["score"]), 4)
    except Exception:
        logger.warning("sentiment: classification failed for text starting %r", text[:50], exc_info=True)
        return None, None


def analyze_article_sentiment(article):
    """Convenience wrapper: sentiment over an article's title + description."""
    text = " ".join(part for part in (article.title, article.description) if part)
    return analyze_sentiment(text)
