import os

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate

from pipeline.dedup import deduplicate
from pipeline.validation import validate_articles
from providers.registry import get_registry

load_dotenv()

groq_api_key = os.getenv("GROQ_API_KEY")

if not groq_api_key:
    raise RuntimeError(
        "GROQ_API_KEY is not set. Copy .env.example to .env and fill in your key."
    )

# Deliberately no eager check for NEWSDATA_API_KEY here (unlike before this
# module became provider-agnostic): the provider registry degrades
# gracefully when a provider is unconfigured or fails (see
# providers/registry.py) rather than the whole app refusing to start. Groq
# still gets an eager check since there's no fallback summarization model.
llm = ChatGroq(api_key=groq_api_key, model="openai/gpt-oss-120b", temperature=0)


def get_news_articles(query, page_size=10, language="en", category=None):
    """Fetches from every enabled provider (NewsData.io, RSS, ...) via the
    provider registry, deduplicates across them, and returns the survivors
    in the same dict shape (title/description/link/pubDate/...) this
    function has always returned -- so app.py/history.py get multi-source
    fetching, deduplication, and provider failover for free, with no
    changes needed on their end.
    """
    registry = get_registry()
    articles = registry.fetch_all(query=query, category=category, language=language, page_size=page_size)
    articles = validate_articles(articles)
    deduplicate(articles)
    return [_to_legacy_dict(a) for a in articles if not a.is_duplicate]


def _to_legacy_dict(article):
    return {
        "title": article.title,
        "description": article.description,
        "link": article.url,
        "pubDate": article.published_at,
        "source_name": article.source_name,
        "provider": article.provider,
    }


def summarize_articles(articles):
    summaries = [a["description"] for a in articles if a.get("description")]
    return " ".join(summaries)


def get_summary(query):
    articles = get_news_articles(query)
    return summarize_articles(articles)


template = """
You are an AI news research assistant. Given the following query and the
provided news article summaries, write a clear, well-organized overall
summary of what's happening, covering the key facts and explaining why
each development is important. Frame significance generally (why it
matters to an informed reader) -- do not frame this as investment,
equity-research, or trading advice.

Query: {query}
Summaries: {summaries}
"""

prompt = PromptTemplate(template=template, input_variables=["query", "summaries"])
llm_chain = prompt | llm


story_summary_template = """
You are summarizing a news story that multiple outlets have covered. Given
the article titles and descriptions below, write:
1. One concise overview sentence.
2. 3-5 bullet points covering the key distinct facts.

Do not editorialize or speculate beyond what the articles state.

Articles:
{articles_text}
"""

story_summary_prompt = PromptTemplate(template=story_summary_template, input_variables=["articles_text"])
story_summary_chain = story_summary_prompt | llm


def generate_story_summary(story_articles):
    """Bullet-point AI summary for a story cluster (roadmap section 13).
    Called only for multi-article stories, and only once per story -- see
    pipeline/ingest.py, which checks db.get_story() for an existing cached
    summary before calling this, so a story is never re-summarized on
    every ingestion cycle.
    """
    articles_text = "\n\n".join(
        f"- {a.source_name}: {a.title}\n  {a.description or ''}" for a in story_articles
    )
    response = story_summary_chain.invoke({"articles_text": articles_text})
    return response.content


story_extras_template = """
You are analyzing a news story covered by multiple sources. Given the
dated, sourced articles below (in chronological order), produce exactly
four sections using the markdown headers shown below, in that order. Base
everything only on what the articles say -- do not speculate or introduce
outside facts.

## Timeline
A short chronological narrative (2-4 sentences) of how coverage of this
story developed over time.

## Coverage Comparison
One line per source, formatted as "- SourceName: what angle or focus that
source's coverage emphasized" (e.g. "- Reuters: economic impact").

## Coverage Perspective
For each source, one line noting its apparent tone (e.g. neutral, urgent,
critical, sympathetic) and which topics, entities, or word choices it
emphasized. This is automated pattern analysis of word choice and
emphasis only -- it does NOT represent a definitive assessment of
editorial bias, and must not be phrased as one. End this section with
exactly this sentence, unchanged: "This is automated analysis of language
patterns, not a definitive assessment of editorial bias."

## Why This Matters
2-3 concise sentences on why this story is significant -- its likely
consequences or broader relevance, grounded in the articles.

Articles (chronological order):
{articles_text}
"""

story_extras_prompt = PromptTemplate(template=story_extras_template, input_variables=["articles_text"])
story_extras_chain = story_extras_prompt | llm

_EXTRAS_SECTION_HEADERS = {
    "## Timeline": "timeline",
    "## Coverage Comparison": "coverage_comparison",
    "## Coverage Perspective": "coverage_perspective",
    "## Why This Matters": "why_matters",
}


def _parse_story_extras(text):
    sections = {"timeline": "", "coverage_comparison": "", "coverage_perspective": "", "why_matters": ""}
    current_key = None
    for line in text.splitlines():
        stripped = line.strip()
        matched_key = next((key for header, key in _EXTRAS_SECTION_HEADERS.items() if stripped.startswith(header)), None)
        if matched_key:
            current_key = matched_key
            continue
        if current_key:
            sections[current_key] += line + "\n"
    return {key: value.strip() for key, value in sections.items()}


def generate_story_extras(story_articles):
    """Timeline + Coverage Comparison + Coverage Perspective + Why This
    Matters (roadmap sections 27/28/29/30) in a single Groq call rather
    than four, to keep LLM calls per ingestion cycle proportional to story
    significance. Called only for "major" stories (3+ articles, a
    stricter bar than the 2+ used for the basic summary) -- see
    pipeline/ingest.py. Coverage Perspective's prompt explicitly forbids
    presenting this as a definitive bias assessment, per the roadmap's own
    caution against unsupported bias claims.
    """
    dated = sorted((a for a in story_articles if a.published_at), key=lambda a: a.published_at)
    ordered = dated or story_articles
    articles_text = "\n\n".join(
        f"- [{a.published_at or 'unknown time'}] {a.source_name}: {a.title}\n  {a.description or ''}"
        for a in ordered
    )
    response = story_extras_chain.invoke({"articles_text": articles_text})
    return _parse_story_extras(response.content)
