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


def close() -> None:
    global _conn
    if _conn:
        _conn.close()
        _conn = None
