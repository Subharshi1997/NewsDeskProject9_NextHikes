from unittest.mock import patch

from pipeline.ingest import _generate_story_extras, _generate_story_summaries
from providers.base import NormalizedArticle


def make_article(**overrides):
    defaults = dict(article_id="1", title="Title", url="https://example.com/a", provider="p", source_name="Source")
    defaults.update(overrides)
    return NormalizedArticle(**defaults)


# --- _generate_story_summaries ---

def test_generate_story_summaries_skips_single_article_stories():
    story_map = {"story-1": [make_article()]}
    with patch("db.get_story", return_value=None), \
         patch("langchain_config.generate_story_summary") as mock_gen:
        result = _generate_story_summaries(story_map)

    assert result == {}
    mock_gen.assert_not_called()


def test_generate_story_summaries_skips_stories_with_existing_summary():
    story_map = {"story-1": [make_article(), make_article(article_id="2")]}
    with patch("db.get_story", return_value={"summary": "Already have one"}), \
         patch("langchain_config.generate_story_summary") as mock_gen:
        result = _generate_story_summaries(story_map)

    assert result == {}
    mock_gen.assert_not_called()


def test_generate_story_summaries_generates_for_new_multi_article_stories():
    articles = [make_article(), make_article(article_id="2")]
    story_map = {"story-1": articles}
    with patch("db.get_story", return_value=None), \
         patch("langchain_config.generate_story_summary", return_value="A summary.") as mock_gen:
        result = _generate_story_summaries(story_map)

    assert result == {"story-1": "A summary."}
    mock_gen.assert_called_once_with(articles)


def test_generate_story_summaries_continues_after_one_failure():
    story_map = {
        "story-1": [make_article(), make_article(article_id="2")],
        "story-2": [make_article(article_id="3"), make_article(article_id="4")],
    }
    with patch("db.get_story", return_value=None), \
         patch("langchain_config.generate_story_summary", side_effect=[RuntimeError("boom"), "OK"]):
        result = _generate_story_summaries(story_map)

    assert result == {"story-2": "OK"}


# --- _generate_story_extras ---

def test_generate_story_extras_requires_three_plus_articles():
    story_map = {"story-1": [make_article(), make_article(article_id="2")]}  # only 2
    with patch("db.get_story", return_value=None), \
         patch("langchain_config.generate_story_extras") as mock_gen:
        result = _generate_story_extras(story_map)

    assert result == {}
    mock_gen.assert_not_called()


def test_generate_story_extras_skips_stories_already_analyzed():
    story_map = {"story-1": [make_article(), make_article(article_id="2"), make_article(article_id="3")]}
    with patch("db.get_story", return_value={"why_matters": "Already analyzed"}), \
         patch("langchain_config.generate_story_extras") as mock_gen:
        result = _generate_story_extras(story_map)

    assert result == {}
    mock_gen.assert_not_called()


def test_generate_story_extras_generates_for_new_major_stories():
    articles = [make_article(), make_article(article_id="2"), make_article(article_id="3")]
    story_map = {"story-1": articles}
    fake_extras = {"timeline": "T", "coverage_comparison": "C", "why_matters": "W"}
    with patch("db.get_story", return_value=None), \
         patch("langchain_config.generate_story_extras", return_value=fake_extras) as mock_gen:
        result = _generate_story_extras(story_map)

    assert result == {"story-1": fake_extras}
    mock_gen.assert_called_once_with(articles)


def test_generate_story_extras_continues_after_failure():
    story_map = {"story-1": [make_article(), make_article(article_id="2"), make_article(article_id="3")]}
    with patch("db.get_story", return_value=None), \
         patch("langchain_config.generate_story_extras", side_effect=RuntimeError("boom")):
        result = _generate_story_extras(story_map)

    assert result == {}
