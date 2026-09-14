from unittest.mock import Mock, patch

import pipeline.entities as entities
from providers.base import NormalizedArticle


def make_article(**overrides):
    defaults = dict(article_id="1", title="Title", url="https://example.com/a", provider="p", source_name="Source")
    defaults.update(overrides)
    return NormalizedArticle(**defaults)


def _fake_ent(text, label):
    e = Mock()
    e.text = text
    e.label_ = label
    return e


def _fake_nlp(ents):
    fake_doc = Mock()
    fake_doc.ents = ents
    return Mock(return_value=fake_doc)


def test_extract_entities_filters_to_relevant_labels():
    fake_nlp = _fake_nlp([_fake_ent("Nvidia", "ORG"), _fake_ent("4%", "PERCENT"), _fake_ent("Jensen Huang", "PERSON")])
    with patch.object(entities, "_get_nlp", return_value=fake_nlp):
        result = entities.extract_entities("some text")

    assert {"text": "Nvidia", "label": "ORG"} in result
    assert {"text": "Jensen Huang", "label": "PERSON"} in result
    assert not any(r["label"] == "PERCENT" for r in result)


def test_extract_entities_deduplicates_case_insensitively():
    fake_nlp = _fake_nlp([_fake_ent("Nvidia", "ORG"), _fake_ent("NVIDIA", "ORG")])
    with patch.object(entities, "_get_nlp", return_value=fake_nlp):
        result = entities.extract_entities("text")
    assert len(result) == 1


def test_extract_entities_skips_blank_entity_text():
    fake_nlp = _fake_nlp([_fake_ent("   ", "ORG"), _fake_ent("Nvidia", "ORG")])
    with patch.object(entities, "_get_nlp", return_value=fake_nlp):
        result = entities.extract_entities("text")
    assert result == [{"text": "Nvidia", "label": "ORG"}]


def test_extract_entities_empty_text_skips_the_model():
    fake_nlp = Mock()
    with patch.object(entities, "_get_nlp", return_value=fake_nlp):
        result = entities.extract_entities("")
    assert result == []
    fake_nlp.assert_not_called()


def test_extract_entities_returns_empty_when_model_unavailable():
    with patch.object(entities, "_get_nlp", return_value=None):
        result = entities.extract_entities("some text")
    assert result == []


def test_extract_entities_handles_model_exception_gracefully():
    fake_nlp = Mock(side_effect=RuntimeError("boom"))
    with patch.object(entities, "_get_nlp", return_value=fake_nlp):
        result = entities.extract_entities("some text")
    assert result == []


def test_extract_article_entities_combines_title_and_description():
    fake_nlp = _fake_nlp([])
    article = make_article(title="Nvidia news", description="about earnings")
    with patch.object(entities, "_get_nlp", return_value=fake_nlp):
        entities.extract_article_entities(article)
    called_text = fake_nlp.call_args[0][0]
    assert "Nvidia news" in called_text
    assert "about earnings" in called_text
