import csv
import io
import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

import analytics
import auth
import db
import saved_stories
import scheduler
from history import add_entry, load_history, save_history
from langchain_config import get_news_articles, llm_chain, summarize_articles
from logging_config import configure_logging
from pipeline.trending import compute_trending
from providers.registry import get_registry

configure_logging()

LANGUAGE_OPTIONS = {
    "English": "en",
    "Spanish": "es",
    "French": "fr",
    "German": "de",
    "Hindi": "hi",
    "Chinese": "zh",
}
CATEGORY_OPTIONS = {
    "Any": None,
    "Business": "business",
    "Technology": "technology",
    "Politics": "politics",
    "World": "world",
    "Science": "science",
    "Top": "top",
}
SENTIMENT_ICONS = {"positive": "🟢", "neutral": "⚪", "negative": "🔴"}
ENTITY_LABELS = {
    "PERSON": "Person", "ORG": "Organization", "GPE": "Place", "LOC": "Location",
    "PRODUCT": "Product", "NORP": "Group", "MONEY": "Financial",
}
TRENDING_WINDOWS = {"24 hours": "24h", "7 days": "7d", "30 days": "30d"}
COUNTRY_WINDOWS = {"24 hours": 1, "7 days": 7, "30 days": 30}
ANALYTICS_SECTIONS = ["Overview", "Sentiment Trends", "Sources", "Topics", "Countries"]
STORY_SENTIMENT_OPTIONS = ["Any", "Positive", "Neutral", "Negative"]
STORY_TIME_WINDOWS = {"Any time": None, "Last 24 hours": 1, "Last 7 days": 7, "Last 30 days": 30}

# Editorial styling -- serif headlines (Merriweather), clean sans body
# (Inter), a restrained masthead-red accent. Targets Streamlit's
# documented data-testid hooks where possible (more stable across
# versions than its internal class names); a version bump that changes
# these would degrade the visual polish, not break functionality.
CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Merriweather:wght@700;900&family=Inter:wght@400;500;600&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}

h1, h2, h3 {
    font-family: 'Merriweather', Georgia, serif !important;
    font-weight: 700 !important;
    color: #1A1A1A;
}

.masthead {
    border-bottom: 3px solid #1A1A1A;
    padding-bottom: 0.75rem;
    margin-bottom: 1.5rem;
}
.masthead-row {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    flex-wrap: wrap;
    gap: 8px;
}
.masthead-title {
    font-family: 'Merriweather', Georgia, serif;
    font-weight: 900;
    font-size: 2.6rem;
    letter-spacing: -0.5px;
    color: #1A1A1A;
    line-height: 1.1;
}
.masthead-date {
    font-family: 'Inter', sans-serif;
    color: #6B6B6B;
    font-size: 0.85rem;
    text-align: right;
    white-space: nowrap;
}

[data-testid="stTabs"] button {
    font-family: 'Inter', sans-serif;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 0.8rem;
}
[data-testid="stTabs"] [aria-selected="true"] {
    color: #9A2323 !important;
    border-bottom-color: #9A2323 !important;
}

div[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 6px !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.07);
}

[data-testid="stMarkdownContainer"] table {
    border-collapse: collapse;
    width: 100%;
    font-size: 0.9rem;
}
[data-testid="stMarkdownContainer"] th {
    background-color: #F2EFE9;
    text-align: left;
    padding: 8px 10px;
    border-bottom: 2px solid #1A1A1A;
    font-family: 'Inter', sans-serif;
}
[data-testid="stMarkdownContainer"] td {
    padding: 8px 10px;
    border-bottom: 1px solid #E5E2DA;
    vertical-align: top;
}

.stButton button[kind="primary"] {
    border-radius: 4px;
    font-weight: 600;
}

.category-pill {
    display: inline-block;
    background-color: #F2EFE9;
    color: #9A2323;
    border: 1px solid #9A2323;
    border-radius: 12px;
    padding: 1px 10px;
    font-size: 0.68rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-right: 6px;
    margin-bottom: 6px;
}

.hero-title {
    font-family: 'Merriweather', Georgia, serif;
    font-weight: 900;
    font-size: 2rem;
    line-height: 1.2;
    color: #1A1A1A;
    margin: 6px 0 4px 0;
}
</style>
"""


def render_masthead():
    today = datetime.now().strftime("%A, %B %d, %Y")
    st.markdown(
        f"""
        <div class="masthead">
            <div class="masthead-row">
                <div class="masthead-title">📰 News Research Tool</div>
                <div class="masthead-date">{today}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_auth_gate():
    """PDF Task 7.1. Only rendered when auth.get_configured_password()
    returns something -- an unconfigured app skips this entirely (see
    auth.py's docstring for why that's the safe default, not a bug).
    """
    st.markdown('<div class="masthead-title">📰 News Research Tool</div>', unsafe_allow_html=True)
    st.caption("Enter the access password to continue.")
    with st.form("auth_form"):
        entered_password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Unlock", type="primary")
    if submitted:
        if auth.check_password(entered_password, auth.get_configured_password()):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")


st.set_page_config(page_title="News Research Tool", page_icon="📰", layout="wide")
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

db.init_db()
scheduler.start_background_ingestion(queries=[None], language="en")

if "history" not in st.session_state:
    st.session_state.history = load_history()
if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "saved_story_ids" not in st.session_state:
    st.session_state.saved_story_ids = set(saved_stories.load_saved())

if not auth.is_authenticated(st.session_state):
    render_auth_gate()
    st.stop()


def toggle_saved(story_id):
    if story_id in st.session_state.saved_story_ids:
        st.session_state.saved_story_ids.discard(story_id)
    else:
        st.session_state.saved_story_ids.add(story_id)
    saved_stories.save_saved(st.session_state.saved_story_ids)


def format_timestamp(iso_string):
    try:
        return datetime.fromisoformat(iso_string).strftime("%b %d, %Y %H:%M UTC")
    except (TypeError, ValueError):
        return ""


def format_sentiment_badge(sentiment_counts):
    """sentiment_counts: db.get_story_sentiment()'s return shape --
    {"positive": {"count": N, "avg_score": ...}, ...}. Shows the dominant
    label as a share of all sentiment-scored articles in the story.
    """
    if not sentiment_counts:
        return None
    total = sum(v["count"] for v in sentiment_counts.values())
    if total == 0:
        return None
    label, stats = max(sentiment_counts.items(), key=lambda kv: kv[1]["count"])
    icon = SENTIMENT_ICONS.get(label, "⚪")
    pct = round(stats["count"] / total * 100)
    return f"{icon} {label.title()} coverage ({pct}% of {total} article{'s' if total != 1 else ''})"


def render_category_pills(category_str):
    if not category_str:
        return
    pieces = [p.strip() for p in category_str.split(",") if p.strip()]
    if not pieces:
        return
    html = "".join(f'<span class="category-pill">{p}</span>' for p in pieces[:3])
    st.markdown(html, unsafe_allow_html=True)


def render_story_card(story, context, hero=False):
    """The single reusable story tile, used by Home (hero + grid), Latest
    Stories (grid), and Saved (grid). `context` must be a distinguishing
    string per call site (e.g. "home_grid", "latest") -- combined with the
    story_id it keeps the Save button's widget key unique even when the
    same story appears on more than one tab in the same render (Streamlit
    renders every tab's content on every rerun, not just the visible one).
    """
    story_id = story["story_id"]
    story_articles = db.get_story_articles(story_id)

    with st.container(border=True):
        thumbnail = story.get("image_url")
        if thumbnail:
            st.image(thumbnail, width="stretch")

        render_category_pills(story.get("primary_category"))

        if hero:
            st.markdown(f'<div class="hero-title">{story["title"]}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f"**{story['title']}**")

        sources = story["source_names"]
        st.caption(f"Covered by {len(sources)} source{'s' if len(sources) != 1 else ''} · {' · '.join(sources)}")

        badge = format_sentiment_badge(db.get_story_sentiment(story_id))
        if badge:
            st.caption(badge)

        if story.get("summary"):
            st.markdown(story["summary"])

        if story.get("why_matters"):
            st.markdown(f"**Why this matters:** {story['why_matters']}")

        has_extras = story.get("timeline") or story.get("coverage_comparison") or story.get("coverage_perspective")
        if has_extras:
            with st.expander("Timeline, comparison & perspective"):
                if story.get("timeline"):
                    st.markdown("**Timeline**")
                    st.write(story["timeline"])
                if story.get("coverage_comparison"):
                    st.markdown("**Coverage comparison**")
                    st.markdown(story["coverage_comparison"])
                if story.get("coverage_perspective"):
                    st.markdown("**Coverage perspective**")
                    st.caption("Automated analysis of language patterns and emphasis -- not a definitive assessment of editorial bias.")
                    st.markdown(story["coverage_perspective"])

        related = db.get_related_stories(story_id, limit=3)
        if related:
            with st.expander(f"Related stories ({len(related)})"):
                for r in related:
                    r_sources = ", ".join(r["source_names"][:3])
                    st.markdown(f"- **{r['title']}**" + (f" · {r_sources}" if r_sources else ""))

        with st.expander("View articles"):
            for i, article in enumerate(story_articles):
                if i > 0:
                    st.divider()

                marker = "⭐ " if article["is_primary"] else ""
                st.markdown(f"**{marker}{article['title']}**")

                if article.get("description"):
                    st.write(article["description"])

                meta_bits = [article["source_name"], article["provider"]]
                if article.get("sentiment"):
                    meta_bits.append(f"{SENTIMENT_ICONS.get(article['sentiment'], '')} {article['sentiment']}")
                st.caption(" · ".join(b for b in meta_bits if b))

                st.markdown(f"🔗 [Read full article]({article['url']})")

                entities = db.get_article_entities(article["id"])
                if entities:
                    tags = ", ".join(
                        f"{e['entity_name']} ({ENTITY_LABELS.get(e['entity_type'], e['entity_type'])})"
                        for e in entities[:6]
                    )
                    st.caption(f"Entities: {tags}")

        is_saved = story_id in st.session_state.saved_story_ids
        if st.button("★ Saved" if is_saved else "☆ Save story", key=f"save_{context}_{story_id}"):
            toggle_saved(story_id)
            st.rerun()


def render_story_grid(stories, context, columns=2):
    cols = st.columns(columns)
    for i, story in enumerate(stories):
        with cols[i % columns]:
            render_story_card(story, context=context, hero=False)


def rows_to_csv(rows, fieldnames):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def rows_to_json(rows):
    return json.dumps(rows, indent=2, ensure_ascii=False)


def search_articles_export_rows(articles):
    return [
        {
            "title": a.get("title"),
            "description": a.get("description"),
            "source_name": a.get("source_name"),
            "url": a.get("link"),
            "published_at": a.get("pubDate"),
        }
        for a in articles
    ]


def stories_export_rows(stories):
    return [
        {
            "title": s["title"],
            "sources": ", ".join(s["source_names"]),
            "article_count": s["article_count"],
            "summary": s.get("summary") or "",
            "why_matters": s.get("why_matters") or "",
            "updated_at": s["updated_at"],
        }
        for s in stories
    ]


@st.cache_data(ttl=300, show_spinner=False)
def cached_trending(window):
    return compute_trending(window=window, top_n=10)


@st.cache_data(ttl=300, show_spinner=False)
def cached_country_volume(days):
    return analytics.country_volume(days=days)


@st.cache_data(ttl=300, show_spinner=False)
def cached_entity_analytics(entity_name):
    return analytics.entity_analytics(entity_name)


@st.cache_data(ttl=900, show_spinner=False)
def fetch_summary_and_articles(query, language, category):
    articles = get_news_articles(query, language=language, category=category)
    summaries = summarize_articles(articles)
    if not articles:
        return "", []
    if not summaries:
        return "No article descriptions were available to summarize.", articles
    response = llm_chain.invoke({"query": query, "summaries": summaries})
    return response.content, articles


render_masthead()

tab_home, tab_search, tab_stories, tab_saved, tab_trending, tab_analytics = st.tabs(
    ["🏠 Home", "🔍 Search", "🗞️ Latest Stories", "⭐ Saved", "📈 Trending", "📊 Analytics"]
)

with tab_home:
    st.caption("Top stories from background ingestion, ranked by source quality, recency, completeness, and coverage diversity.")
    home_stories = db.get_stories(limit=7, order_by="quality_score")
    if not home_stories:
        st.info("No stories ingested yet — the background job runs on a schedule (see sidebar for its status). Check back shortly.")
    else:
        render_story_card(home_stories[0], context="home_hero", hero=True)
        rest = home_stories[1:]
        if rest:
            st.divider()
            render_story_grid(rest, context="home_grid", columns=2)

    st.divider()
    st.subheader("Trending Now")
    home_trending = cached_trending("24h")[:5]
    if home_trending:
        for item in home_trending:
            label = ENTITY_LABELS.get(item["entity_type"], item["entity_type"])
            st.markdown(
                f"**{item['entity_name']}** _{label}_ — {item['volume']} articles "
                f"({item['growth_pct']:+.0f}% vs. prior 24h)"
            )
    else:
        st.caption("Not enough ingestion history yet to compute trends.")

with tab_search:
    with st.container(border=True):
        query = st.text_input("Query", placeholder="e.g. Nvidia earnings, Federal Reserve rate decision")
        filter_col1, filter_col2 = st.columns(2)
        with filter_col1:
            language_label = st.selectbox("Language", list(LANGUAGE_OPTIONS.keys()))
        with filter_col2:
            category_label = st.selectbox("Category", list(CATEGORY_OPTIONS.keys()))
        language = LANGUAGE_OPTIONS[language_label]
        category = CATEGORY_OPTIONS[category_label]
        submitted = st.button("Get News", type="primary", width="stretch")

    if submitted:
        if not query:
            st.warning("Please enter a query.")
            st.session_state.last_result = None
        else:
            try:
                with st.spinner("Fetching news and generating summary..."):
                    summary_text, articles = fetch_summary_and_articles(query, language, category)
            except requests.exceptions.RequestException as e:
                st.error(f"Could not reach the news service. Please try again shortly. ({e})")
                st.session_state.last_result = None
            except RuntimeError as e:
                st.error(f"News service returned an error: {e}")
                st.session_state.last_result = None
            except Exception as e:
                st.error(f"Something went wrong while generating the summary: {e}")
                st.session_state.last_result = None
            else:
                if not articles:
                    st.warning("No articles found for this query.")
                    st.session_state.last_result = None
                else:
                    st.session_state.last_result = {
                        "query": query,
                        "summary": summary_text,
                        "articles": articles,
                    }
                    st.session_state.history = add_entry(
                        st.session_state.history, query, summary_text, articles
                    )
                    save_history(st.session_state.history)

    if st.session_state.last_result:
        result = st.session_state.last_result
        st.divider()

        with st.container(border=True):
            st.subheader("Summary")
            st.write(result["summary"])
            st.download_button(
                "Download summary",
                data=result["summary"],
                file_name="summary.txt",
                mime="text/plain",
            )

        with st.container(border=True):
            st.subheader(f"Sources ({len(result['articles'])})")
            export_col1, export_col2 = st.columns(2)
            export_rows = search_articles_export_rows(result["articles"])
            with export_col1:
                st.download_button(
                    "Export sources (CSV)", data=rows_to_csv(export_rows, list(export_rows[0].keys())),
                    file_name="sources.csv", mime="text/csv",
                )
            with export_col2:
                st.download_button(
                    "Export sources (JSON)", data=rows_to_json(export_rows),
                    file_name="sources.json", mime="application/json",
                )
            for article in result["articles"]:
                title = article.get("title")
                link = article.get("link")
                if title and link:
                    st.markdown(f"**[{title}]({link})**")
                    meta_bits = [b for b in (article.get("source_name"), format_timestamp(article.get("pubDate"))) if b]
                    if meta_bits:
                        st.caption(" · ".join(meta_bits))

with tab_stories:
    st.caption(
        "Populated by a background ingestion pass across every enabled provider "
        "(NewsData.io, NewsAPI, GNews + configured RSS feeds), deduplicated, "
        "clustered, and enriched with sentiment + entities."
    )

    with st.expander("🔍 Filters"):
        filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
        with filter_col1:
            stories_category_label = st.selectbox("Category", list(CATEGORY_OPTIONS.keys()), key="stories_category")
        with filter_col2:
            stories_sentiment_label = st.selectbox("Sentiment", STORY_SENTIMENT_OPTIONS, key="stories_sentiment")
        with filter_col3:
            stories_source_filter = st.text_input("Source contains", key="stories_source", placeholder="e.g. Reuters")
        with filter_col4:
            stories_window_label = st.selectbox("Time range", list(STORY_TIME_WINDOWS.keys()), key="stories_window")

    stories_category = CATEGORY_OPTIONS[stories_category_label]
    stories_sentiment = None if stories_sentiment_label == "Any" else stories_sentiment_label.lower()
    stories_since = None
    stories_days = STORY_TIME_WINDOWS[stories_window_label]
    if stories_days:
        stories_since = (datetime.now(timezone.utc) - timedelta(days=stories_days)).isoformat()

    stories = db.get_stories(
        limit=20, category=stories_category, sentiment=stories_sentiment,
        source_name=stories_source_filter or None, since=stories_since,
    )

    if stories:
        export_col1, export_col2 = st.columns(2)
        export_rows = stories_export_rows(stories)
        with export_col1:
            st.download_button(
                "Export stories (CSV)", data=rows_to_csv(export_rows, list(export_rows[0].keys())),
                file_name="stories.csv", mime="text/csv",
            )
        with export_col2:
            st.download_button(
                "Export stories (JSON)", data=rows_to_json(export_rows),
                file_name="stories.json", mime="application/json",
            )

    if not stories:
        st.info("No stories match these filters yet — try widening them, or check back once the background job completes another cycle.")
    else:
        render_story_grid(stories, context="latest", columns=2)

with tab_saved:
    st.caption("Stories you've saved from this app. Saved locally to this machine (no login needed) -- see docs/PROJECT_AUDIT.md's Phase 4 notes.")
    saved_ids = list(st.session_state.saved_story_ids)
    saved = db.get_stories_by_ids(saved_ids)
    if not saved:
        st.info("No saved stories yet — use the ☆ Save story button on any story to add it here.")
    else:
        render_story_grid(saved, context="saved", columns=2)

with tab_trending:
    st.caption(
        "Ranked by growth vs. the prior window, volume, recency, and source diversity — "
        "not just raw article count. Built from entities extracted during background ingestion."
    )
    window_label = st.radio("Window", list(TRENDING_WINDOWS.keys()), horizontal=True)
    window = TRENDING_WINDOWS[window_label]

    trending_results = cached_trending(window)
    if not trending_results:
        st.info(
            "Not enough ingestion history yet to compute trends for this window. "
            "The background job needs a few cycles to build up data."
        )
    else:
        for item in trending_results:
            with st.container(border=True):
                col1, col2 = st.columns([3, 1])
                with col1:
                    label = ENTITY_LABELS.get(item["entity_type"], item["entity_type"])
                    st.markdown(f"**{item['entity_name']}** · _{label}_")
                    st.caption(
                        f"{item['volume']} articles ({item['growth_pct']:+.0f}% vs. prior {window_label.lower()}) "
                        f"· {item['source_diversity']} sources"
                    )
                with col2:
                    st.metric("Momentum", f"{item['trending_score']:.2f}")

with tab_analytics:
    section = st.radio("Section", ANALYTICS_SECTIONS, horizontal=True, label_visibility="collapsed")
    st.divider()

    if section == "Overview":
        summary = analytics.volume_summary()
        col1, col2, col3 = st.columns(3)
        col1.metric("Articles Today", summary["today"])
        col2.metric("Articles This Week", summary["this_week"])
        col3.metric("Articles This Month", summary["this_month"])

        volume = db.get_volume_by_day(days=30)
        if volume:
            st.subheader("News Volume Over Time (30 days)")
            st.area_chart(pd.DataFrame(volume).set_index("day")["count"])

        col1, col2 = st.columns(2)
        with col1:
            categories = db.get_top_categories(limit=10)
            if categories:
                st.subheader("Top Categories")
                st.bar_chart(pd.DataFrame(categories).set_index("category")["count"], horizontal=True)
        with col2:
            top_sources = db.get_top_sources(limit=10)
            if top_sources:
                st.subheader("Top Sources")
                df = pd.DataFrame(top_sources).set_index("source_name")["article_count"]
                st.bar_chart(df, horizontal=True)

        if not volume and not categories and not top_sources:
            st.info("No ingested data yet — check back once the background job completes a cycle.")

    elif section == "Sentiment Trends":
        st.caption("Share of positive/neutral/negative coverage per day, over the last 30 days.")
        trend = db.get_sentiment_trend_by_day(days=30)
        if not trend:
            st.info("No sentiment-scored articles yet.")
        else:
            df = pd.DataFrame(trend).pivot(index="day", columns="sentiment", values="count").fillna(0)
            for col in ("positive", "neutral", "negative"):
                if col not in df.columns:
                    df[col] = 0
            st.line_chart(df[["positive", "neutral", "negative"]])

    elif section == "Sources":
        st.caption("Articles published, average importance score, average sentiment, and distinct story coverage per source.")
        sources = db.get_top_sources(limit=25)
        if not sources:
            st.info("No ingested data yet.")
        else:
            df = pd.DataFrame(sources).rename(columns={
                "source_name": "Source", "article_count": "Articles",
                "avg_quality": "Avg Importance", "avg_sentiment_score": "Avg Sentiment",
                "story_count": "Stories Covered",
            })
            df["Avg Importance"] = df["Avg Importance"].round(3)
            df["Avg Sentiment"] = df["Avg Sentiment"].round(3)
            st.dataframe(df, width="stretch", hide_index=True)

    elif section == "Topics":
        st.caption(
            "Per-entity drill-down: volume, growth, sentiment, top sources, and historical trend. "
            "Operates over extracted entities (people/orgs/places/...), not full topic modeling — see docs/NLP.md."
        )
        top_entities = db.get_top_entities(limit=30)
        if not top_entities:
            st.info("No entities extracted yet.")
        else:
            options = [e["entity_name"] for e in top_entities]
            picked = st.selectbox("Entity", options)
            data = cached_entity_analytics(picked)

            col1, col2, col3 = st.columns(3)
            col1.metric("Volume (24h)", data["volume_24h"], delta=f"{data['growth_pct_24h']:+.0f}%")
            col2.metric("Source diversity (24h)", data["source_diversity_24h"])
            dominant_tone = "—"
            if data["sentiment"]:
                dominant_tone = max(data["sentiment"].items(), key=lambda kv: kv[1]["count"])[0].title()
            col3.metric("Dominant tone", dominant_tone)

            if data["daily_volume"]:
                st.subheader(f"Historical volume: {picked}")
                st.bar_chart(pd.DataFrame(data["daily_volume"]).set_index("day")["count"])

            if data["top_sources"]:
                st.subheader("Top sources covering this entity")
                st.dataframe(pd.DataFrame(data["top_sources"]), width="stretch", hide_index=True)

    elif section == "Countries":
        window_label = st.radio("Window", list(COUNTRY_WINDOWS.keys()), horizontal=True, key="country_window")
        days = COUNTRY_WINDOWS[window_label]
        st.caption(
            "Article volume by country. Country data is inconsistently populated across providers and "
            "normalized best-effort (2-letter codes, full names, and multi-country fields are all merged) — "
            "coverage is partial, not exhaustive. See docs/ANALYTICS.md."
        )
        countries = cached_country_volume(days)
        if not countries:
            st.info("No country-tagged articles in this window yet.")
        else:
            df = pd.DataFrame(countries)
            fig = px.choropleth(
                df, locations="iso3", color="count", hover_name="name",
                color_continuous_scale="Blues", locationmode="ISO-3",
            )
            fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=420)
            st.plotly_chart(fig, width="stretch")
            st.dataframe(
                df.rename(columns={"name": "Country", "count": "Articles"})[["Country", "Articles"]],
                width="stretch", hide_index=True,
            )

with st.sidebar:
    if auth.get_configured_password():
        if st.button("🔒 Log out", width="stretch"):
            st.session_state.authenticated = False
            st.rerun()
        st.divider()

    st.header("🕘 Query History")
    if st.session_state.history:
        for entry in reversed(st.session_state.history[-20:]):
            with st.expander(entry["query"]):
                st.caption(format_timestamp(entry.get("timestamp")))
                st.write(entry["summary"])
                for source in entry.get("sources", []):
                    st.markdown(f"- [{source['title']}]({source['link']})")
        if st.button("Clear history", width="stretch"):
            st.session_state.history = []
            save_history(st.session_state.history)
            st.rerun()
    else:
        st.caption("No queries yet.")

    st.divider()
    st.header("📡 Provider Status")
    st.caption(f"Background ingestion: {'running' if scheduler.is_running() else 'stopped'}")
    for name, status in get_registry().status_report().items():
        icon = {"ok": "🟢", "error": "🔴", "disabled": "⚪", "unknown": "⚪"}.get(status["status"], "⚪")
        with st.expander(f"{icon} {name}"):
            st.caption(f"Status: {status['status']}")
            if status["last_success"]:
                st.caption(f"Last success: {format_timestamp(status['last_success'])}")
            if status["last_failure"]:
                st.caption(f"Last failure: {format_timestamp(status['last_failure'])}")
            if status["last_error"]:
                st.caption(f"Error: {status['last_error']}")
            st.caption(f"Articles fetched (last run): {status['articles_fetched']}")
            if status["response_time_ms"]:
                st.caption(f"Response time: {status['response_time_ms']:.0f} ms")
            if status["rate_limited"]:
                st.caption("⚠️ Rate limit encountered")

st.caption(
    "Data via NewsData.io, NewsAPI, GNews + RSS · Summaries via Groq (openai/gpt-oss-120b) "
    "· Sentiment via cardiffnlp/twitter-roberta-base-sentiment-latest · Entities via spaCy"
)
