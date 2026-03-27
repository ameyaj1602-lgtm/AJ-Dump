"""
Data ingestion layer — fetches articles from RSS feeds and NewsAPI concurrently.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import feedparser
import httpx

import config
import database

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NewsAgent/1.0; +https://github.com/news-agent)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


@dataclass
class RawArticle:
    title: str
    url: str
    source: str
    published: str = ""
    description: str = ""
    hash: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self.hash = database.compute_hash(self.title, self.url)


# ── RSS Fetching ──────────────────────────────────────────────────────────────

async def _fetch_rss_feed(client: httpx.AsyncClient, url: str) -> list[RawArticle]:
    """Fetch a single RSS feed and return parsed articles."""
    try:
        resp = await client.get(url, timeout=15)
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)
        source = feed.feed.get("title", url)[:60]
        articles = []
        for entry in feed.entries[:30]:  # cap per feed
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            if not title:
                continue
            articles.append(
                RawArticle(
                    title=title,
                    url=link,
                    source=source,
                    published=entry.get("published", ""),
                    description=entry.get("summary", "")[:500],
                )
            )
        logger.info("RSS  %-40s → %d items", source[:40], len(articles))
        return articles
    except Exception as exc:
        logger.warning("RSS fetch failed for %s: %s", url, exc)
        return []


async def fetch_rss() -> list[RawArticle]:
    """Fetch all configured RSS feeds concurrently."""
    async with httpx.AsyncClient(headers=_HEADERS, follow_redirects=True) as client:
        tasks = [_fetch_rss_feed(client, url) for url in config.RSS_FEEDS]
        results = await asyncio.gather(*tasks)
    return [a for batch in results for a in batch]


# ── NewsAPI Fetching ──────────────────────────────────────────────────────────

async def fetch_newsapi() -> list[RawArticle]:
    """Fetch top headlines from NewsAPI (if key is configured)."""
    if not config.NEWS_API_KEY:
        return []

    articles: list[RawArticle] = []
    async with httpx.AsyncClient(headers=_HEADERS, follow_redirects=True) as client:
        try:
            resp = await client.get(
                "https://newsapi.org/v2/top-headlines",
                params={
                    "apiKey": config.NEWS_API_KEY,
                    "language": "en",
                    "pageSize": 50,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("articles", []):
                title = (item.get("title") or "").strip()
                if not title:
                    continue
                articles.append(
                    RawArticle(
                        title=title,
                        url=item.get("url", ""),
                        source=item.get("source", {}).get("name", "NewsAPI"),
                        published=item.get("publishedAt", ""),
                        description=(item.get("description") or "")[:500],
                    )
                )
            logger.info("NewsAPI → %d items", len(articles))
        except Exception as exc:
            logger.warning("NewsAPI fetch failed: %s", exc)
    return articles


# ── Public API ────────────────────────────────────────────────────────────────

async def fetch_all() -> list[RawArticle]:
    """Fetch from all sources, deduplicate against DB, return only new articles."""
    rss_task = fetch_rss()
    api_task = fetch_newsapi()
    rss_articles, api_articles = await asyncio.gather(rss_task, api_task)

    all_articles = rss_articles + api_articles

    # Deduplicate: drop articles already in DB
    new_articles = [a for a in all_articles if not database.exists(a.hash)]

    # Deduplicate within batch (keep first seen)
    seen: set[str] = set()
    unique: list[RawArticle] = []
    for a in new_articles:
        if a.hash not in seen:
            seen.add(a.hash)
            unique.append(a)

    logger.info(
        "Fetched %d total, %d new after dedup", len(all_articles), len(unique)
    )
    return unique
