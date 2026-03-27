"""
SQLite storage layer — stores articles and handles deduplication via content hashing.
"""

import hashlib
import sqlite3
import time
from typing import Optional

import config

_conn: Optional[sqlite3.Connection] = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(config.DB_PATH)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
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
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_articles_hash ON articles(hash)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_articles_created ON articles(created_at)
    """)
    conn.commit()


def compute_hash(title: str, url: str = "") -> str:
    """Generate a deduplication hash from title (normalised) + url."""
    normalised = title.lower().strip()
    raw = f"{normalised}|{url.strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def exists(article_hash: str) -> bool:
    row = _get_conn().execute(
        "SELECT 1 FROM articles WHERE hash = ?", (article_hash,)
    ).fetchone()
    return row is not None


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
            (
                article_hash,
                title,
                url,
                source,
                summary,
                tags,
                priority,
                cluster_id,
                published,
                time.time(),
            ),
        )
        _get_conn().commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_recent(limit: int = 20) -> list[dict]:
    rows = _get_conn().execute(
        "SELECT * FROM articles ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def close() -> None:
    global _conn
    if _conn:
        _conn.close()
        _conn = None
