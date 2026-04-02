"""
Data ingestion layer — fetches articles from RSS feeds and NewsAPI concurrently.
Features: HTML cleanup, retry on failure, fuzzy dedup, robust error handling.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from html import unescape
from typing import Optional

import feedparser
import httpx

import config
import database

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


def _clean_text(text: str) -> str:
    """Clean HTML entities and excessive whitespace."""
    text = unescape(text)
    text = re.sub(r"<[^>]+>", "", text)  # strip any HTML tags
    text = re.sub(r"\s+", " ", text).strip()
    return text


@dataclass
class RawArticle:
    title: str
    url: str
    source: str
    published: str = ""
    description: str = ""
    hash: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self.title = _clean_text(self.title)
        self.description = _clean_text(self.description)
        self.hash = database.compute_hash(self.title, self.url)


# ── RSS Fetching ──────────────────────────────────────────────────────────────

async def _fetch_rss_feed(client: httpx.AsyncClient, url: str) -> list[RawArticle]:
    """Fetch a single RSS feed with one retry on failure."""
    for attempt in range(2):
        try:
            resp = await client.get(url, timeout=15)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)
            source = feed.feed.get("title", url)[:60]
            articles = []
            for entry in feed.entries[:25]:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                if not title or len(title) < 10:
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
            if attempt == 0:
                await asyncio.sleep(3)
            else:
                logger.warning("RSS failed: %s → %s", url[:50], str(exc)[:80])
    return []


async def fetch_rss() -> list[RawArticle]:
    async with httpx.AsyncClient(headers=_HEADERS, follow_redirects=True) as client:
        tasks = [_fetch_rss_feed(client, url) for url in config.RSS_FEEDS]
        results = await asyncio.gather(*tasks)
    return [a for batch in results for a in batch]


# ── NewsAPI Fetching ──────────────────────────────────────────────────────────

async def fetch_newsapi() -> list[RawArticle]:
    if not config.NEWS_API_KEY:
        return []

    articles: list[RawArticle] = []
    async with httpx.AsyncClient(headers=_HEADERS, follow_redirects=True) as client:
        try:
            resp = await client.get(
                "https://newsapi.org/v2/top-headlines",
                params={"apiKey": config.NEWS_API_KEY, "language": "en", "pageSize": 50},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("articles", []):
                title = (item.get("title") or "").strip()
                if not title or len(title) < 10:
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
            logger.warning("NewsAPI failed: %s", str(exc)[:80])
    return articles


# ── Fuzzy Dedup ───────────────────────────────────────────────────────────────

def _fuzzy_dedup(articles: list[RawArticle]) -> list[RawArticle]:
    """Remove articles with >80% title similarity within the batch."""
    kept: list[RawArticle] = []
    kept_titles: list[str] = []
    for a in articles:
        normalised = a.title.lower()
        is_dupe = False
        for existing in kept_titles:
            if SequenceMatcher(None, normalised, existing).ratio() > 0.80:
                is_dupe = True
                break
        if not is_dupe:
            kept.append(a)
            kept_titles.append(normalised)
    return kept


# ── Public API ────────────────────────────────────────────────────────────────

async def fetch_all() -> list[RawArticle]:
    """Fetch from all sources, deduplicate, return only new articles."""
    from scraper import scrape_all

    rss_task = fetch_rss()
    api_task = fetch_newsapi()
    scrape_task = scrape_all()
    rss_articles, api_articles, scraped_articles = await asyncio.gather(
        rss_task, api_task, scrape_task
    )

    all_articles = rss_articles + api_articles + scraped_articles

    # Hash dedup against DB
    new_articles = [a for a in all_articles if not database.exists(a.hash)]

    # Hash dedup within batch
    seen: set[str] = set()
    unique: list[RawArticle] = []
    for a in new_articles:
        if a.hash not in seen:
            seen.add(a.hash)
            unique.append(a)

    # Fuzzy title dedup within batch
    unique = _fuzzy_dedup(unique)

    # Cross-cycle fuzzy dedup against DB (check top candidates only)
    final: list[RawArticle] = []
    for a in unique:
        if not database.find_similar_title(a.title):
            final.append(a)

    logger.info("Fetched %d total, %d new after dedup", len(all_articles), len(final))
    return final
