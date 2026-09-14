import logging

logger = logging.getLogger("news_research_tool.pipeline.entities")

MODEL_NAME = "en_core_web_sm"

# spaCy's own label set, filtered to what's useful here. Known
# simplification: spaCy doesn't distinguish "company" from other
# organization types, or "country" from city/state (GPE covers both) --
# a real company/country taxonomy would need a second classification pass,
# not attempted here. "Stocks" (ticker symbols) aren't a spaCy label at all
# and are deferred to Phase 7 (Market Intelligence), where resolving a
# company mention to a ticker actually belongs.
RELEVANT_LABELS = {"PERSON", "ORG", "GPE", "LOC", "PRODUCT", "NORP", "MONEY"}

_nlp = None
_load_failed = False


def _get_nlp():
    """Lazily loads the spaCy model on first real use -- keeps `import
    pipeline.entities` cheap for anything that doesn't actually extract
    entities (e.g. most tests).
    """
    global _nlp, _load_failed
    if _nlp is not None or _load_failed:
        return _nlp
    try:
        import spacy
        _nlp = spacy.load(MODEL_NAME)
    except Exception:
        logger.exception(
            "entities: failed to load spaCy model %r -- entity extraction will be skipped for this process",
            MODEL_NAME,
        )
        _load_failed = True
    return _nlp


def extract_entities(text):
    """Returns a list of {"text": ..., "label": ...} dicts, deduplicated by
    (case-insensitive text, label). Empty list for empty text or if the
    model couldn't be loaded. No cross-article entity resolution/linking
    (e.g. "Nvidia" vs "NVIDIA Corp" are treated as distinct) -- a known
    limitation, not attempted in this pass.
    """
    if not text or not text.strip():
        return []
    nlp = _get_nlp()
    if nlp is None:
        return []
    try:
        doc = nlp(text)
    except Exception:
        logger.warning("entities: extraction failed for text starting %r", text[:50], exc_info=True)
        return []

    seen = set()
    entities = []
    for ent in doc.ents:
        if ent.label_ not in RELEVANT_LABELS:
            continue
        name = ent.text.strip()
        if not name:
            continue
        key = (name.lower(), ent.label_)
        if key in seen:
            continue
        seen.add(key)
        entities.append({"text": name, "label": ent.label_})
    return entities


def extract_article_entities(article):
    """Convenience wrapper: entities from an article's title + description."""
    text = " ".join(part for part in (article.title, article.description) if part)
    return extract_entities(text)
