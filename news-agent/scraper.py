"""
Real-time scraper — pulls live data from news websites, Reddit, and Twitter/X
without needing any API keys. Uses plain HTTP requests + HTML parsing.
"""

import asyncio
import logging
import re
from datetime import datetime

import httpx

from fetcher import RawArticle

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ── Reddit (no API key needed — uses public JSON endpoints) ──────────────────

async def scrape_reddit(client: httpx.AsyncClient) -> list[RawArticle]:
    """Scrape top posts from news-related subreddits via Reddit's public JSON API."""
    subreddits = [
        "worldnews",
        "technology",
        "business",
        "news",
        "artificial",
        "startups",
    ]
    articles: list[RawArticle] = []

    for sub in subreddits:
        try:
            resp = await client.get(
                f"https://www.reddit.com/r/{sub}/hot.json?limit=15",
                headers={**_HEADERS, "Accept": "application/json"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            for post in data.get("data", {}).get("children", []):
                d = post.get("data", {})
                title = d.get("title", "").strip()
                if not title or d.get("stickied"):
                    continue
                # Skip self-posts with no real content
                url = d.get("url", "")
                if "reddit.com/r/" in url and "/comments/" in url:
                    url = f"https://reddit.com{d.get('permalink', '')}"

                articles.append(
                    RawArticle(
                        title=title,
                        url=url,
                        source=f"r/{sub}",
                        published=datetime.utcfromtimestamp(
                            d.get("created_utc", 0)
                        ).isoformat()
                        if d.get("created_utc")
                        else "",
                        description=(d.get("selftext") or "")[:500],
                    )
                )
            logger.info("Reddit  r/%-20s → %d posts", sub, len(articles))
        except Exception as exc:
            logger.warning("Reddit r/%s scrape failed: %s", sub, exc)

    return articles


# ── Twitter/X Trending (via Nitter mirrors — no API key needed) ──────────────

async def scrape_twitter_trends(client: httpx.AsyncClient) -> list[RawArticle]:
    """Scrape trending topics from Twitter/X via public sources."""
    articles: list[RawArticle] = []

    # Method 1: Use Twstalker or similar public viewer
    # Method 2: Scrape trending from Twitter's explore page data
    # We use a reliable public trends endpoint
    try:
        # Trends24 provides Twitter trending data publicly
        resp = await client.get(
            "https://trends24.in/united-states/",
            headers=_HEADERS,
            timeout=15,
        )
        if resp.status_code == 200:
            text = resp.text
            # Extract trending topics from the HTML
            # Look for trend links in the page
            trend_pattern = re.compile(
                r'<a[^>]*href="(/united-states/\#[^"]*)"[^>]*>([^<]+)</a>',
                re.IGNORECASE,
            )
            # Also try the more common trend card pattern
            card_pattern = re.compile(
                r'<li[^>]*>\s*<a[^>]*>([^<]+)</a>',
                re.IGNORECASE,
            )
            trends = set()
            for match in trend_pattern.finditer(text):
                trend = match.group(2).strip()
                if trend and len(trend) > 2:
                    trends.add(trend)
            for match in card_pattern.finditer(text):
                trend = match.group(1).strip()
                if trend and trend.startswith("#") and len(trend) > 2:
                    trends.add(trend)

            for trend in list(trends)[:20]:
                search_query = trend.replace("#", "").replace(" ", "+")
                articles.append(
                    RawArticle(
                        title=f"Trending on X: {trend}",
                        url=f"https://x.com/search?q={search_query}",
                        source="Twitter/X Trends",
                        description=f"Currently trending on Twitter/X: {trend}",
                    )
                )
            logger.info("Twitter trends → %d topics", len(articles))
    except Exception as exc:
        logger.warning("Twitter trends scrape failed: %s", exc)

    return articles


# ── Hacker News API (free, no key needed) ────────────────────────────────────

async def scrape_hackernews(client: httpx.AsyncClient) -> list[RawArticle]:
    """Fetch top stories from Hacker News official API (free, no key)."""
    articles: list[RawArticle] = []
    try:
        resp = await client.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            timeout=10,
        )
        resp.raise_for_status()
        story_ids = resp.json()[:25]  # top 25

        # Fetch stories in parallel
        tasks = []
        for sid in story_ids:
            tasks.append(
                client.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{sid}.json",
                    timeout=10,
                )
            )
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        for r in responses:
            if isinstance(r, Exception):
                continue
            try:
                item = r.json()
                title = item.get("title", "").strip()
                if not title:
                    continue
                articles.append(
                    RawArticle(
                        title=title,
                        url=item.get("url", f"https://news.ycombinator.com/item?id={item.get('id', '')}"),
                        source="Hacker News",
                        published=datetime.utcfromtimestamp(
                            item.get("time", 0)
                        ).isoformat()
                        if item.get("time")
                        else "",
                        description=f"Score: {item.get('score', 0)} | Comments: {item.get('descendants', 0)}",
                    )
                )
            except Exception:
                continue

        logger.info("Hacker News API → %d stories", len(articles))
    except Exception as exc:
        logger.warning("Hacker News API scrape failed: %s", exc)

    return articles


# ── Google News scraping (HTML fallback when RSS is blocked) ─────────────────

async def scrape_google_news(client: httpx.AsyncClient) -> list[RawArticle]:
    """Scrape Google News search results for breaking news."""
    articles: list[RawArticle] = []
    queries = ["breaking news", "top stories today"]

    for query in queries:
        try:
            resp = await client.get(
                "https://news.google.com/search",
                params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
                headers=_HEADERS,
                timeout=15,
            )
            if resp.status_code != 200:
                continue

            # Extract article titles from Google News HTML
            # Google News uses <a class="...">title</a> patterns
            title_pattern = re.compile(
                r'<a[^>]*class="[^"]*JtKRv[^"]*"[^>]*>([^<]+)</a>',
                re.IGNORECASE,
            )
            for match in title_pattern.finditer(resp.text):
                title = match.group(1).strip()
                if title and len(title) > 10:
                    articles.append(
                        RawArticle(
                            title=title,
                            url="https://news.google.com",
                            source="Google News",
                            description="",
                        )
                    )

            logger.info("Google News scrape '%s' → %d items", query, len(articles))
        except Exception as exc:
            logger.warning("Google News scrape failed: %s", exc)

    return articles


# ── BBC / Reuters / Al Jazeera headline scraping ─────────────────────────────

async def scrape_news_sites(client: httpx.AsyncClient) -> list[RawArticle]:
    """Scrape headlines from major news websites."""
    articles: list[RawArticle] = []

    sites = [
        {
            "url": "https://www.bbc.com/news",
            "source": "BBC News",
            # BBC uses data-testid attributes for headlines
            "patterns": [
                re.compile(r'<h2[^>]*data-testid="card-headline"[^>]*>([^<]+)</h2>', re.I),
                re.compile(r'<h3[^>]*>([^<]{20,120})</h3>', re.I),
            ],
        },
        {
            "url": "https://www.aljazeera.com/",
            "source": "Al Jazeera",
            "patterns": [
                re.compile(r'<h3[^>]*class="[^"]*article-card[^"]*"[^>]*>\s*<a[^>]*>\s*<span>([^<]+)</span>', re.I),
                re.compile(r'<h3[^>]*>[^<]*<a[^>]*>([^<]{20,120})</a>', re.I),
            ],
        },
    ]

    for site in sites:
        try:
            resp = await client.get(
                site["url"], headers=_HEADERS, timeout=15, follow_redirects=True
            )
            if resp.status_code != 200:
                continue

            found = set()
            for pattern in site["patterns"]:
                for match in pattern.finditer(resp.text):
                    title = match.group(1).strip()
                    # Clean up HTML entities
                    title = title.replace("&amp;", "&").replace("&#x27;", "'").replace("&quot;", '"')
                    if title and len(title) > 15 and title not in found:
                        found.add(title)
                        articles.append(
                            RawArticle(
                                title=title,
                                url=site["url"],
                                source=site["source"],
                                description="",
                            )
                        )

            logger.info("%-15s → %d headlines", site["source"], len(found))
        except Exception as exc:
            logger.warning("%s scrape failed: %s", site["source"], exc)

    return articles


# ── Public API ────────────────────────────────────────────────────────────────

async def scrape_all() -> list[RawArticle]:
    """Run all scrapers concurrently and return combined results."""
    async with httpx.AsyncClient(headers=_HEADERS, follow_redirects=True) as client:
        results = await asyncio.gather(
            scrape_reddit(client),
            scrape_twitter_trends(client),
            scrape_hackernews(client),
            scrape_google_news(client),
            scrape_news_sites(client),
            return_exceptions=True,
        )

    articles: list[RawArticle] = []
    for result in results:
        if isinstance(result, list):
            articles.extend(result)
        elif isinstance(result, Exception):
            logger.warning("Scraper error: %s", result)

    logger.info("Scrapers total → %d raw articles", len(articles))
    return articles
