"""
SQLite storage layer — stores articles and handles deduplication.
Features: hash dedup, fuzzy title matching, auto-cleanup, crash resilience.
"""

import hashlib
import re
import sqlite3
import time
from difflib import SequenceMatcher
from typing import Optional

import config

_conn: Optional[sqlite3.Connection] = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        try:
            _conn.execute("SELECT 1")
            return _conn
        except Exception:
            _conn = None

    _conn = sqlite3.connect(config.DB_PATH)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA busy_timeout=5000")
    _create_tables(_conn)
    return _conn


def _create_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            hash        TEXT UNIQUE NOT NULL,
            title       TEXT NOT NULL,
            url         TEXT,
            source      TEXT,
            summary     TEXT,
            tags        TEXT,
            priority    INTEGER DEFAULT 0,
            cluster_id  TEXT,
            published   TEXT,
            created_at  REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_hash ON articles(hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_created ON articles(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_priority ON articles(priority)")
    conn.commit()


def _normalise_title(title: str) -> str:
    """Aggressively normalise title for dedup: lowercase, strip punctuation, articles."""
    t = title.lower().strip()
    t = re.sub(r"^(breaking\s*(news)?[:\-–]?\s*)", "", t)
    t = re.sub(r"[^\w\s]", "", t)  # strip punctuation
    t = re.sub(r"\b(the|a|an|is|are|was|were|in|on|at|to|for|of|and|or)\b", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def compute_hash(title: str, url: str = "") -> str:
    """Generate dedup hash from normalised title only (not URL)."""
    normalised = _normalise_title(title)
    return hashlib.sha256(normalised.encode()).hexdigest()[:16]


def exists(article_hash: str) -> bool:
    row = _get_conn().execute(
        "SELECT 1 FROM articles WHERE hash = ?", (article_hash,)
    ).fetchone()
    return row is not None


def find_similar_title(title: str, threshold: float = 0.80) -> bool:
    """Check if a similar title exists in recent articles (last 500)."""
    normalised = _normalise_title(title)
    rows = _get_conn().execute(
        "SELECT title FROM articles ORDER BY created_at DESC LIMIT 500"
    ).fetchall()
    for row in rows:
        existing = _normalise_title(row["title"])
        if SequenceMatcher(None, normalised, existing).ratio() >= threshold:
            return True
    return False


def insert_article(
    article_hash: str,
    title: str,
    url: str = "",
    source: str = "",
    summary: str = "",
    tags: str = "",
    priority: int = 0,
    cluster_id: str = "",
    published: str = "",
) -> bool:
    """Insert an article. Returns True if inserted, False if duplicate."""
    try:
        _get_conn().execute(
            """INSERT INTO articles
               (hash, title, url, source, summary, tags, priority, cluster_id, published, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (article_hash, title, url, source, summary, tags, priority, cluster_id, published, time.time()),
        )
        _get_conn().commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_recent(limit: int = 30, min_priority: int = 0) -> list[dict]:
    rows = _get_conn().execute(
        "SELECT * FROM articles WHERE priority >= ? ORDER BY created_at DESC LIMIT ?",
        (min_priority, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def cleanup_old(max_age_hours: int = 48) -> int:
    """Delete articles older than max_age_hours. Returns count deleted."""
    cutoff = time.time() - (max_age_hours * 3600)
    cursor = _get_conn().execute("DELETE FROM articles WHERE created_at < ?", (cutoff,))
    _get_conn().commit()
    return cursor.rowcount


def get_article_count() -> int:
    row = _get_conn().execute("SELECT COUNT(*) as c FROM articles").fetchone()
    return row["c"] if row else 0


def get_tag_distribution() -> list[dict]:
    """Return tag counts across all articles."""
    rows = _get_conn().execute(
        "SELECT tags FROM articles WHERE tags IS NOT NULL AND tags != ''"
    ).fetchall()
    from collections import Counter
    tag_counts: Counter = Counter()
    for row in rows:
        for tag in row["tags"].split(","):
            tag = tag.strip()
            if tag:
                tag_counts[tag] += 1
    return [{"tag": t, "count": c} for t, c in tag_counts.most_common(20)]


def get_source_stats() -> list[dict]:
    """Return article count and avg priority per source."""
    rows = _get_conn().execute("""
        SELECT source,
               COUNT(*) as count,
               ROUND(AVG(priority), 1) as avg_priority,
               MAX(priority) as max_priority
        FROM articles
        GROUP BY source
        ORDER BY count DESC
        LIMIT 30
    """).fetchall()
    return [dict(r) for r in rows]


def get_priority_distribution() -> dict:
    """Return count of articles in each priority band."""
    rows = _get_conn().execute("""
        SELECT
            SUM(CASE WHEN priority >= 70 THEN 1 ELSE 0 END) as high,
            SUM(CASE WHEN priority >= 50 AND priority < 70 THEN 1 ELSE 0 END) as medium,
            SUM(CASE WHEN priority >= 30 AND priority < 50 THEN 1 ELSE 0 END) as low,
            SUM(CASE WHEN priority < 30 THEN 1 ELSE 0 END) as minimal
        FROM articles
    """).fetchone()
    return dict(rows) if rows else {"high": 0, "medium": 0, "low": 0, "minimal": 0}


def get_timeline(hours: int = 48, bucket_minutes: int = 60) -> list[dict]:
    """Return article counts bucketed by time."""
    import time as _time
    cutoff = _time.time() - (hours * 3600)
    rows = _get_conn().execute("""
        SELECT
            CAST((created_at - ?) / ? AS INTEGER) as bucket,
            COUNT(*) as count,
            ROUND(AVG(priority), 1) as avg_priority
        FROM articles
        WHERE created_at >= ?
        GROUP BY bucket
        ORDER BY bucket
    """, (cutoff, bucket_minutes * 60, cutoff)).fetchall()
    results = []
    for r in rows:
        bucket_start = cutoff + r["bucket"] * bucket_minutes * 60
        from datetime import datetime
        results.append({
            "time": datetime.fromtimestamp(bucket_start).strftime("%Y-%m-%d %H:%M"),
            "count": r["count"],
            "avg_priority": r["avg_priority"],
        })
    return results


def get_clusters() -> list[dict]:
    """Return clusters with their articles, sorted by avg priority."""
    rows = _get_conn().execute("""
        SELECT cluster_id,
               COUNT(*) as count,
               ROUND(AVG(priority), 1) as avg_priority,
               MAX(priority) as top_priority,
               GROUP_CONCAT(title, '|||') as titles
        FROM articles
        WHERE cluster_id IS NOT NULL AND cluster_id != ''
        GROUP BY cluster_id
        HAVING count > 1
        ORDER BY avg_priority DESC
        LIMIT 20
    """).fetchall()
    results = []
    for r in rows:
        titles = (r["titles"] or "").split("|||")[:5]
        results.append({
            "cluster_id": r["cluster_id"],
            "count": r["count"],
            "avg_priority": r["avg_priority"],
            "top_priority": r["top_priority"],
            "sample_titles": titles,
        })
    return results


def search_articles(query: str, limit: int = 30) -> list[dict]:
    """Full-text search across title and summary."""
    pattern = f"%{query}%"
    rows = _get_conn().execute(
        "SELECT * FROM articles WHERE title LIKE ? OR summary LIKE ? ORDER BY priority DESC LIMIT ?",
        (pattern, pattern, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_source_quality_scores() -> dict[str, float]:
    """Return avg priority per source from last 24h — used to auto-boost good sources."""
    import time as _time
    cutoff = _time.time() - 86400
    rows = _get_conn().execute("""
        SELECT source, AVG(priority) as avg_p, COUNT(*) as cnt
        FROM articles
        WHERE created_at >= ? AND priority > 0
        GROUP BY source
        HAVING cnt >= 3
        ORDER BY avg_p DESC
    """, (cutoff,)).fetchall()
    return {r["source"]: round(r["avg_p"], 1) for r in rows}


def close() -> None:
    global _conn
    if _conn:
        _conn.close()
        _conn = None
