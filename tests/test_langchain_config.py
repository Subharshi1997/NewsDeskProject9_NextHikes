from unittest.mock import Mock, patch

import langchain_config as lc
from providers.base import NormalizedArticle


def make_article(**overrides):
    defaults = dict(article_id="1", title="Title", url="https://example.com/a", provider="newsdata", source_name="Source")
    defaults.update(overrides)
    return NormalizedArticle(**defaults)


def test_summarize_articles_joins_descriptions():
    articles = [
        {"description": "First article summary."},
        {"description": "Second article summary."},
    ]
    result = lc.summarize_articles(articles)
    assert result == "First article summary. Second article summary."


def test_summarize_articles_skips_missing_description():
    articles = [
        {"description": "Has a description."},
        {"description": None},
        {"title": "No description key at all"},
    ]
    result = lc.summarize_articles(articles)
    assert result == "Has a description."


def test_summarize_articles_empty_list():
    assert lc.summarize_articles([]) == ""


def test_get_news_articles_delegates_to_registry_and_returns_legacy_dicts():
    article = make_article(
        title="Nvidia beats earnings", description="Strong quarter.",
        url="https://example.com/story", published_at="2026-09-07T18:16:00+00:00",
        source_name="cnbc", provider="newsdata",
    )
    fake_registry = Mock()
    fake_registry.fetch_all = Mock(return_value=[article])

    with patch.object(lc, "get_registry", return_value=fake_registry):
        result = lc.get_news_articles("nvidia earnings", language="en", category="business")

    fake_registry.fetch_all.assert_called_once_with(
        query="nvidia earnings", category="business", language="en", page_size=10,
    )
    assert result == [
        {
            "title": "Nvidia beats earnings",
            "description": "Strong quarter.",
            "link": "https://example.com/story",
            "pubDate": "2026-09-07T18:16:00+00:00",
            "source_name": "cnbc",
            "provider": "newsdata",
        }
    ]


def test_get_news_articles_deduplicates_across_providers():
    a1 = make_article(title="Same story", url="https://example.com/story?utm_source=fb", provider="newsdata")
    a2 = make_article(title="Same story (rss copy)", url="https://example.com/story", provider="rss", article_id="2")
    fake_registry = Mock()
    fake_registry.fetch_all = Mock(return_value=[a1, a2])

    with patch.object(lc, "get_registry", return_value=fake_registry):
        result = lc.get_news_articles("query")

    assert len(result) == 1


def test_get_summary_combines_fetch_and_summarize():
    fake_articles = [{"description": "Revenue grew 10%."}, {"description": "Guidance raised."}]
    with patch.object(lc, "get_news_articles", return_value=fake_articles):
        result = lc.get_summary("apple earnings")

    assert result == "Revenue grew 10%. Guidance raised."


def test_parse_story_extras_splits_on_headers():
    text = (
        "## Timeline\n"
        "First reports emerged Monday. By Wednesday, official confirmation followed.\n"
        "\n"
        "## Coverage Comparison\n"
        "- Reuters: economic impact\n"
        "- The Hindu: policy implications\n"
        "\n"
        "## Coverage Perspective\n"
        "- Reuters: neutral tone, emphasized market data.\n"
        "This is automated analysis of language patterns, not a definitive assessment of editorial bias.\n"
        "\n"
        "## Why This Matters\n"
        "This could affect borrowing costs and inflation expectations.\n"
    )
    result = lc._parse_story_extras(text)

    assert result["timeline"].startswith("First reports emerged Monday.")
    assert "- Reuters: economic impact" in result["coverage_comparison"]
    assert "- The Hindu: policy implications" in result["coverage_comparison"]
    assert "neutral tone" in result["coverage_perspective"]
    assert "not a definitive assessment of editorial bias" in result["coverage_perspective"]
    assert result["why_matters"] == "This could affect borrowing costs and inflation expectations."


def test_parse_story_extras_handles_missing_sections():
    text = "## Timeline\nOnly a timeline was provided.\n"
    result = lc._parse_story_extras(text)

    assert result["timeline"] == "Only a timeline was provided."
    assert result["coverage_comparison"] == ""
    assert result["coverage_perspective"] == ""
    assert result["why_matters"] == ""


def test_generate_story_extras_orders_articles_chronologically_and_parses_response():
    later = make_article(
        title="Later report", source_name="BBC", published_at="2026-09-10T12:00:00+00:00", article_id="2",
        url="https://example.com/b",
    )
    earlier = make_article(
        title="Earlier report", source_name="Reuters", published_at="2026-09-10T08:00:00+00:00",
        url="https://example.com/a",
    )
    fake_response = Mock(content="## Timeline\nStory developed.\n\n## Coverage Comparison\n- Reuters: x\n\n## Why This Matters\nIt matters.\n")
    fake_chain = Mock()
    fake_chain.invoke = Mock(return_value=fake_response)

    with patch.object(lc, "story_extras_chain", fake_chain):
        result = lc.generate_story_extras([later, earlier])

    called_text = fake_chain.invoke.call_args[0][0]["articles_text"]
    assert called_text.index("Earlier report") < called_text.index("Later report")
    assert result["why_matters"] == "It matters."
