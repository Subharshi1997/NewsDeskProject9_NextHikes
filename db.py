import contextlib
import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pipeline.scoring import SourceScorer

logger = logging.getLogger("news_research_tool.db")

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "news.db"

# Design note: no `article_story` junction table. Clustering (pipeline.clustering)
# partitions articles into stories — each article belongs to exactly one
# story — so a single story_id foreign key on `articles` covers it. By
# contrast, `article_entities` below IS a many-to-many junction table --
# one article mentions many entities, one entity appears in many articles --
# that relationship is real, unlike story/article. `providers` /
# `rss_sources` still aren't DB tables: they're config-file-driven
# (config/rss_sources.json, env vars), so mirroring them into the DB would
# just be a second source of truth.
TABLES_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_name TEXT PRIMARY KEY,
    quality_score REAL,
    country TEXT,
    category TEXT,
    first_seen TEXT,
    last_seen TEXT
);

CREATE TABLE IF NOT EXISTS stories (
    story_id TEXT PRIMARY KEY,
    title TEXT,
    summary TEXT,
    timeline TEXT,
    coverage_comparison TEXT,
    coverage_perspective TEXT,
    why_matters TEXT,
    created_at TEXT,
    updated_at TEXT,
    article_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id TEXT,
    title TEXT NOT NULL,
    description TEXT,
    content TEXT,
    url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    image_url TEXT,
    source_name TEXT,
    source_url TEXT,
    provider TEXT NOT NULL,
    author TEXT,
    published_at TEXT,
    fetched_at TEXT,
    language TEXT,
    country TEXT,
    category TEXT,
    keywords TEXT,
    content_hash TEXT,
    story_id TEXT,
    quality_score REAL,
    is_primary INTEGER DEFAULT 1,
    sentiment TEXT,
    sentiment_score REAL,
    UNIQUE(canonical_url),
    FOREIGN KEY(story_id) REFERENCES stories(story_id),
    FOREIGN KEY(source_name) REFERENCES sources(source_name)
);

CREATE TABLE IF NOT EXISTS entities (
    entity_name TEXT PRIMARY KEY,
    entity_type TEXT,
    mention_count INTEGER DEFAULT 0,
    first_seen TEXT,
    last_seen TEXT
);

CREATE TABLE IF NOT EXISTS article_entities (
    article_row_id INTEGER NOT NULL,
    entity_name TEXT NOT NULL,
    entity_type TEXT,
    PRIMARY KEY (article_row_id, entity_name),
    FOREIGN KEY (article_row_id) REFERENCES articles(id),
    FOREIGN KEY (entity_name) REFERENCES entities(entity_name)
);
"""

# Indexes are created separately, AFTER _run_column_migrations -- on a
# database file that already existed before the sentiment/summary columns
# were added, CREATE TABLE IF NOT EXISTS is a no-op (the table's already
# there), so those columns wouldn't exist yet if an index on them ran as
# part of the same script as the (skipped) table creation.
INDEXES_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at);
CREATE INDEX IF NOT EXISTS idx_articles_source_name ON articles(source_name);
CREATE INDEX IF NOT EXISTS idx_articles_story_id ON articles(story_id);
CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category);
CREATE INDEX IF NOT EXISTS idx_articles_language ON articles(language);
CREATE INDEX IF NOT EXISTS idx_articles_country ON articles(country);
CREATE INDEX IF NOT EXISTS idx_articles_sentiment ON articles(sentiment);
CREATE INDEX IF NOT EXISTS idx_article_entities_entity_name ON article_entities(entity_name);
"""

# Columns added after the original schema shipped. CREATE TABLE IF NOT
# EXISTS won't add these to a database file that already exists from
# before this change, so init_db() runs this as a defensive migration --
# a full migration framework (e.g. Alembic) would be overkill for a
# single-file local SQLite DB with one owner.
_COLUMN_MIGRATIONS = {
    "articles": {"sentiment": "TEXT", "sentiment_score": "REAL"},
    "stories": {
        "summary": "TEXT", "timeline": "TEXT", "coverage_comparison": "TEXT",
        "coverage_perspective": "TEXT", "why_matters": "TEXT",
    },
}


def _db_path():
    return os.getenv("NEWS_DB_PATH", str(DEFAULT_DB_PATH))


@contextlib.contextmanager
def get_connection():
    conn = sqlite3.connect(_db_path(), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _run_column_migrations(conn):
    for table, columns in _COLUMN_MIGRATIONS.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, coltype in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {coltype}")
                logger.info("db: migrated -- added %s.%s", table, name)


def init_db():
    with get_connection() as conn:
        conn.executescript(TABLES_SCHEMA)
        _run_column_migrations(conn)
        conn.executescript(INDEXES_SCHEMA)
    logger.info("db: schema ready at %s", _db_path())


def ensure_source(conn, source_name, quality_score=None, country=None, category=None):
    """Idempotent: creates/refreshes the source row. Must run before any
    article referencing it is inserted (articles.source_name is a FK).
    """
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO sources (source_name, quality_score, country, category, first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_name) DO UPDATE SET
            quality_score = excluded.quality_score,
            last_seen = excluded.last_seen
        """,
        (source_name, quality_score, country, category, now, now),
    )


def ensure_story(conn, story_id, title, summary=None):
    """Idempotent: creates the story row if missing, with article_count=0.
    Must run before any article referencing it is inserted (articles.story_id
    is a FK). Count is bumped separately, only on an actual new insert —
    see _touch_story. `summary` is only written when provided (the caller
    only passes one when it just generated a fresh AI summary for this
    story), so an existing cached summary is never clobbered with NULL.
    """
    now = datetime.now(timezone.utc).isoformat()
    if summary:
        conn.execute(
            """
            INSERT INTO stories (story_id, title, summary, created_at, updated_at, article_count)
            VALUES (?, ?, ?, ?, ?, 0)
            ON CONFLICT(story_id) DO UPDATE SET summary = excluded.summary
            """,
            (story_id, title, summary, now, now),
        )
    else:
        conn.execute(
            """
            INSERT INTO stories (story_id, title, created_at, updated_at, article_count)
            VALUES (?, ?, ?, ?, 0)
            ON CONFLICT(story_id) DO NOTHING
            """,
            (story_id, title, now, now),
        )


def _touch_story(conn, story_id):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE stories SET updated_at = ?, article_count = article_count + 1 WHERE story_id = ?",
        (now, story_id),
    )


def get_story(story_id):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM stories WHERE story_id = ?", (story_id,)).fetchone()
    return dict(row) if row else None


def set_story_extras(conn, story_id, timeline=None, coverage_comparison=None,
                      coverage_perspective=None, why_matters=None):
    """UPDATE-only (not upsert): the story row is guaranteed to already
    exist by the time this runs in store_articles (ensure_story always
    runs first). Only columns with a non-empty value are touched, so a
    story that already has these cached is never clobbered on a cycle
    that didn't regenerate them.
    """
    updates, params = [], []
    if timeline:
        updates.append("timeline = ?")
        params.append(timeline)
    if coverage_comparison:
        updates.append("coverage_comparison = ?")
        params.append(coverage_comparison)
    if coverage_perspective:
        updates.append("coverage_perspective = ?")
        params.append(coverage_perspective)
    if why_matters:
        updates.append("why_matters = ?")
        params.append(why_matters)
    if not updates:
        return
    params.append(story_id)
    conn.execute(f"UPDATE stories SET {', '.join(updates)} WHERE story_id = ?", params)


def insert_article(conn, article):
    """Returns the new row's id on success, or None if it was already
    present (canonical_url UNIQUE constraint) — a defense-in-depth backstop
    behind pipeline.dedup's Level-1 check, not a replacement for it.
    """
    try:
        cursor = conn.execute(
            """
            INSERT INTO articles (
                article_id, title, description, content, url, canonical_url,
                image_url, source_name, source_url, provider, author,
                published_at, fetched_at, language, country, category,
                keywords, content_hash, story_id, quality_score, is_primary,
                sentiment, sentiment_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article.article_id, article.title, article.description, article.content,
                article.url, article.canonical_url, article.image_url, article.source_name,
                article.source_url, article.provider, article.author, article.published_at,
                article.fetched_at, article.language, article.country, article.category,
                json.dumps(article.keywords or []), article.content_hash, article.story_id,
                article.quality_score, int(bool(article.is_primary)),
                article.sentiment, article.sentiment_score,
            ),
        )
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None


def ensure_entity(conn, entity_name, entity_type):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO entities (entity_name, entity_type, mention_count, first_seen, last_seen)
        VALUES (?, ?, 1, ?, ?)
        ON CONFLICT(entity_name) DO UPDATE SET
            mention_count = mention_count + 1,
            last_seen = excluded.last_seen
        """,
        (entity_name, entity_type, now, now),
    )


def link_article_entities(conn, article_row_id, entities):
    """entities: list of {"text": ..., "label": ...} dicts, as produced by
    pipeline.entities.extract_entities.
    """
    for ent in entities:
        name, etype = ent["text"], ent["label"]
        ensure_entity(conn, name, etype)
        conn.execute(
            """
            INSERT INTO article_entities (article_row_id, entity_name, entity_type)
            VALUES (?, ?, ?)
            ON CONFLICT(article_row_id, entity_name) DO NOTHING
            """,
            (article_row_id, name, etype),
        )


def get_article_entities(article_row_id):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT entity_name, entity_type FROM article_entities WHERE article_row_id = ?",
            (article_row_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_entity_activity(since):
    """Distinct (entity_name, entity_type) pairs mentioned by any article
    published at or after `since` (ISO string). Used by pipeline.trending
    to find candidates worth scoring, without scanning every entity ever seen.
    """
    sql = """
        SELECT DISTINCT ae.entity_name, ae.entity_type
        FROM article_entities ae
        JOIN articles a ON a.id = ae.article_row_id
        WHERE a.published_at >= ?
    """
    with get_connection() as conn:
        rows = conn.execute(sql, (since,)).fetchall()
    return [(row["entity_name"], row["entity_type"]) for row in rows]


def get_entity_window_stats(entity_name, since, until):
    """Article count, distinct source count, and most recent publish time
    for one entity within [since, until). Powers pipeline.trending's
    volume/diversity/recency signals for a specific time window.
    """
    sql = """
        SELECT COUNT(*) AS count,
               COUNT(DISTINCT a.source_name) AS distinct_sources,
               MAX(a.published_at) AS latest_published_at
        FROM article_entities ae
        JOIN articles a ON a.id = ae.article_row_id
        WHERE ae.entity_name = ? AND a.published_at >= ? AND a.published_at < ?
    """
    with get_connection() as conn:
        row = conn.execute(sql, (entity_name, since, until)).fetchone()
    if not row or row["count"] == 0:
        return {"count": 0, "distinct_sources": 0, "latest_published_at": None}
    return dict(row)


def get_story_sentiment(story_id):
    """Sentiment label counts + average score across a story's articles,
    for display (e.g. "Mostly Positive coverage"). Computed on demand from
    per-article sentiment rather than a persisted aggregate, so it's always
    in sync with the underlying article rows.
    """
    sql = """
        SELECT sentiment, COUNT(*) AS count, AVG(sentiment_score) AS avg_score
        FROM articles
        WHERE story_id = ? AND sentiment IS NOT NULL
        GROUP BY sentiment
    """
    with get_connection() as conn:
        rows = conn.execute(sql, (story_id,)).fetchall()
    return {row["sentiment"]: {"count": row["count"], "avg_score": row["avg_score"]} for row in rows}


def store_articles(articles, source_scorer=None, story_summaries=None, story_extras=None):
    """Persist non-duplicate articles (and their sources/stories/entities)
    in one transaction. Duplicates are skipped, not stored — "don't store
    four copies" is enforced here, not just flagged. Returns (inserted, skipped).

    story_summaries: optional {story_id: summary_text} for stories that
    were just freshly summarized this cycle (see pipeline/ingest.py) --
    only those get their `stories.summary` written/overwritten.
    story_extras: optional {story_id: {"timeline":..., "coverage_comparison":...,
    "why_matters":...}} for "major" (3+ article) stories freshly analyzed
    this cycle -- same never-clobber-on-a-skip-cycle behavior as summaries.
    """
    source_scorer = source_scorer or SourceScorer()
    story_summaries = story_summaries or {}
    story_extras = story_extras or {}
    inserted = skipped = 0
    extras_applied = set()
    with get_connection() as conn:
        for article in articles:
            if article.is_duplicate:
                skipped += 1
                continue

            # Source/story rows must exist before the article that
            # references them (FK constraints), so this always runs first.
            if article.source_name:
                source_quality = source_scorer.score(article.source_name)
                ensure_source(conn, article.source_name, source_quality, article.country, article.category)
            if article.story_id:
                ensure_story(conn, article.story_id, article.title, summary=story_summaries.get(article.story_id))
                if article.story_id in story_extras and article.story_id not in extras_applied:
                    set_story_extras(conn, article.story_id, **story_extras[article.story_id])
                    extras_applied.add(article.story_id)

            row_id = insert_article(conn, article)
            if row_id is None:
                skipped += 1
                continue
            inserted += 1
            # article_count is only bumped here -- on an actual new insert --
            # so a re-run over the same data doesn't inflate it.
            if article.story_id:
                _touch_story(conn, article.story_id)
            if article.entities:
                link_article_entities(conn, row_id, article.entities)
    logger.info("db: stored %d articles, skipped %d (duplicates or already present)", inserted, skipped)
    return inserted, skipped


def get_articles(category=None, country=None, language=None, source_name=None, story_id=None,
                  sentiment=None, query=None, limit=50):
    clauses, params = [], []
    for column, value in (
        ("category", category), ("country", country), ("language", language),
        ("source_name", source_name), ("story_id", story_id), ("sentiment", sentiment),
    ):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    if query:
        clauses.append("(title LIKE ? OR description LIKE ?)")
        like = f"%{query}%"
        params.extend([like, like])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM articles {where} ORDER BY published_at DESC LIMIT ?"
    params.append(limit)

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


_STORY_ORDER_COLUMNS = {
    "updated_at": "s.updated_at DESC",
    "quality_score": "a.quality_score DESC",
}

_STORY_COLUMNS = """
    s.story_id, s.title, s.summary, s.timeline, s.coverage_comparison,
    s.coverage_perspective, s.why_matters, s.created_at, s.updated_at, s.article_count,
    a.image_url, a.category AS primary_category, a.quality_score AS primary_quality_score,
    (SELECT GROUP_CONCAT(DISTINCT a2.source_name) FROM articles a2 WHERE a2.story_id = s.story_id) AS source_names
"""


def get_stories(limit=20, category=None, sentiment=None, source_name=None, since=None, order_by="updated_at"):
    """Roadmap #41 "Smart Search": category/sentiment/source/date filters
    over the ingested story corpus. Filters are evaluated against each
    story's *primary* article (pipeline.scoring.select_primary always
    marks exactly one per story) -- a story with mixed-sentiment coverage
    is filtered by its best-version article's sentiment, not "matches if
    any article does", which would be a much fuzzier definition.
    source_names in the result still aggregates every article in the
    story (via a subquery), not just the primary one that filters matched on.

    order_by="quality_score" surfaces the best-scoring stories first (used
    for the homepage hero/grid); "updated_at" (default) is the plain
    "most recently touched" ordering the Latest Stories tab uses.
    """
    clauses, params = ["a.is_primary = 1"], []
    if category:
        clauses.append("a.category LIKE ?")
        params.append(f"%{category}%")
    if sentiment:
        clauses.append("a.sentiment = ?")
        params.append(sentiment)
    if source_name:
        clauses.append("a.source_name LIKE ?")
        params.append(f"%{source_name}%")
    if since:
        clauses.append("COALESCE(a.published_at, a.fetched_at) >= ?")
        params.append(since)
    where = " AND ".join(clauses)
    order = _STORY_ORDER_COLUMNS.get(order_by, _STORY_ORDER_COLUMNS["updated_at"])

    sql = f"""
        SELECT {_STORY_COLUMNS}
        FROM stories s
        JOIN articles a ON a.story_id = s.story_id AND {where}
        GROUP BY s.story_id
        ORDER BY {order}
        LIMIT ?
    """
    params.append(limit)
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_story(row) for row in rows]


def get_stories_by_ids(story_ids):
    """Unordered lookup by story_id list, for the Saved Stories view."""
    if not story_ids:
        return []
    placeholders = ",".join("?" * len(story_ids))
    sql = f"""
        SELECT {_STORY_COLUMNS}
        FROM stories s
        JOIN articles a ON a.story_id = s.story_id AND a.is_primary = 1
        WHERE s.story_id IN ({placeholders})
        GROUP BY s.story_id
        ORDER BY s.updated_at DESC
    """
    with get_connection() as conn:
        rows = conn.execute(sql, story_ids).fetchall()
    return [_row_to_story(row) for row in rows]


def _row_to_story(row):
    d = dict(row)
    d["source_names"] = d["source_names"].split(",") if d["source_names"] else []
    return d


def get_related_stories(story_id, limit=5):
    """Other stories sharing at least one extracted entity with this one,
    ranked by how many entities they share -- a cheap "related stories"
    signal that reuses Phase 2's entity data instead of needing new
    infrastructure. No deep-linking (Streamlit has no per-story routing
    yet -- see PROJECT_AUDIT.md's Technical Debt), so this surfaces
    titles/sources for context, not clickable jumps.
    """
    sql = """
        SELECT s2.story_id, s2.title,
               (SELECT GROUP_CONCAT(DISTINCT a3.source_name) FROM articles a3 WHERE a3.story_id = s2.story_id) AS source_names,
               COUNT(DISTINCT ae2.entity_name) AS shared_entities
        FROM article_entities ae1
        JOIN articles a1 ON a1.id = ae1.article_row_id AND a1.story_id = ?
        JOIN article_entities ae2 ON ae2.entity_name = ae1.entity_name
        JOIN articles a2 ON a2.id = ae2.article_row_id AND a2.story_id != ?
        JOIN stories s2 ON s2.story_id = a2.story_id
        GROUP BY s2.story_id
        ORDER BY shared_entities DESC
        LIMIT ?
    """
    with get_connection() as conn:
        rows = conn.execute(sql, (story_id, story_id, limit)).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        d["source_names"] = d["source_names"].split(",") if d["source_names"] else []
        results.append(d)
    return results


def get_story_articles(story_id):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM articles WHERE story_id = ? ORDER BY is_primary DESC, quality_score DESC",
            (story_id,),
        ).fetchall()
    return [dict(row) for row in rows]


# --- Phase 3: analytics aggregations ---
# All of these read COALESCE(published_at, fetched_at) as the effective
# article date, so an article with no publish date (a real, fairly common
# case -- see pipeline.validation) still counts toward volume/trend charts
# using when it was actually ingested.

def get_article_count(since=None):
    clauses, params = [], []
    if since:
        clauses.append("COALESCE(published_at, fetched_at) >= ?")
        params.append(since)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM articles {where}", params).fetchone()[0]


def get_volume_by_day(days=30, category=None, source_name=None):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    clauses = ["COALESCE(published_at, fetched_at) >= ?"]
    params = [since]
    if category:
        clauses.append("category = ?")
        params.append(category)
    if source_name:
        clauses.append("source_name = ?")
        params.append(source_name)
    where = " AND ".join(clauses)
    # substr(..., 1, 10) grabs "YYYY-MM-DD" from our fixed ISO8601 storage
    # format -- simpler and more reliable than relying on SQLite's date()
    # function to parse a "+00:00"-suffixed timestamp.
    sql = f"""
        SELECT substr(COALESCE(published_at, fetched_at), 1, 10) AS day, COUNT(*) AS count
        FROM articles WHERE {where} GROUP BY day ORDER BY day
    """
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [{"day": row["day"], "count": row["count"]} for row in rows]


def get_top_categories(limit=10, since=None):
    """Some providers (NewsData.io) tag one article with multiple
    categories joined into a single comma-separated field (e.g. "top,
    politics") -- the same multi-value pattern seen in the country field
    (see analytics.normalize_country_field). Split and re-aggregated in
    Python rather than grouped raw in SQL, so "top, politics" contributes
    to both "top" and "politics" instead of forming its own bogus
    compound category.
    """
    clauses, params = ["category IS NOT NULL"], []
    if since:
        clauses.append("COALESCE(published_at, fetched_at) >= ?")
        params.append(since)
    where = " AND ".join(clauses)
    sql = f"SELECT category, COUNT(*) AS count FROM articles WHERE {where} GROUP BY category"
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    totals = {}
    for row in rows:
        for piece in row["category"].split(","):
            name = piece.strip()
            if name:
                totals[name] = totals.get(name, 0) + row["count"]

    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    return [{"category": name, "count": count} for name, count in ranked[:limit]]


def get_top_sources(limit=10, since=None):
    clauses, params = [], []
    if since:
        clauses.append("COALESCE(published_at, fetched_at) >= ?")
        params.append(since)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT source_name,
               COUNT(*) AS article_count,
               AVG(quality_score) AS avg_quality,
               AVG(sentiment_score) AS avg_sentiment_score,
               COUNT(DISTINCT story_id) AS story_count
        FROM articles {where}
        GROUP BY source_name
        ORDER BY article_count DESC
        LIMIT ?
    """
    params.append(limit)
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def get_country_field_counts(since=None):
    """Raw (unnormalized) country field value -> article count. The field
    itself may hold a 2-letter code, a lowercase full name, or a
    comma-separated list of many countries -- see analytics.normalize_country_field
    for the cleanup step this feeds into.
    """
    clauses, params = ["country IS NOT NULL", "country != ''"], []
    if since:
        clauses.append("COALESCE(published_at, fetched_at) >= ?")
        params.append(since)
    where = " AND ".join(clauses)
    sql = f"SELECT country, COUNT(*) AS count FROM articles WHERE {where} GROUP BY country"
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [(row["country"], row["count"]) for row in rows]


def get_sentiment_trend_by_day(days=30, category=None, source_name=None):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    clauses = ["COALESCE(published_at, fetched_at) >= ?", "sentiment IS NOT NULL"]
    params = [since]
    if category:
        clauses.append("category = ?")
        params.append(category)
    if source_name:
        clauses.append("source_name = ?")
        params.append(source_name)
    where = " AND ".join(clauses)
    sql = f"""
        SELECT substr(COALESCE(published_at, fetched_at), 1, 10) AS day, sentiment, COUNT(*) AS count
        FROM articles WHERE {where} GROUP BY day, sentiment ORDER BY day
    """
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [{"day": row["day"], "sentiment": row["sentiment"], "count": row["count"]} for row in rows]


def get_top_entities(limit=30):
    sql = "SELECT entity_name, entity_type, mention_count FROM entities ORDER BY mention_count DESC LIMIT ?"
    with get_connection() as conn:
        rows = conn.execute(sql, (limit,)).fetchall()
    return [dict(row) for row in rows]


def get_entity_volume_by_day(entity_name, days=30):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    sql = """
        SELECT substr(a.published_at, 1, 10) AS day, COUNT(*) AS count
        FROM article_entities ae
        JOIN articles a ON a.id = ae.article_row_id
        WHERE ae.entity_name = ? AND a.published_at >= ?
        GROUP BY day ORDER BY day
    """
    with get_connection() as conn:
        rows = conn.execute(sql, (entity_name, since)).fetchall()
    return [{"day": row["day"], "count": row["count"]} for row in rows]


def get_entity_top_sources(entity_name, limit=5):
    sql = """
        SELECT a.source_name, COUNT(*) AS count
        FROM article_entities ae
        JOIN articles a ON a.id = ae.article_row_id
        WHERE ae.entity_name = ?
        GROUP BY a.source_name ORDER BY count DESC LIMIT ?
    """
    with get_connection() as conn:
        rows = conn.execute(sql, (entity_name, limit)).fetchall()
    return [{"source_name": row["source_name"], "count": row["count"]} for row in rows]


def get_entity_sentiment(entity_name):
    sql = """
        SELECT a.sentiment, COUNT(*) AS count, AVG(a.sentiment_score) AS avg_score
        FROM article_entities ae
        JOIN articles a ON a.id = ae.article_row_id
        WHERE ae.entity_name = ? AND a.sentiment IS NOT NULL
        GROUP BY a.sentiment
    """
    with get_connection() as conn:
        rows = conn.execute(sql, (entity_name,)).fetchall()
    return {row["sentiment"]: {"count": row["count"], "avg_score": row["avg_score"]} for row in rows}
