"""
Real-time scraper — pulls live data from news sites, Reddit, Twitter/X, HN.
Features: per-scraper timeouts, HTML cleanup, expanded sources.
"""

import asyncio
import logging
import re
from datetime import datetime
from html import unescape

import httpx

from fetcher import RawArticle

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ── Reddit ────────────────────────────────────────────────────────────────────

async def scrape_reddit(client: httpx.AsyncClient) -> list[RawArticle]:
    subreddits = [
        "worldnews", "technology", "business", "news",
        "artificial", "startups", "science", "economics",
        "geopolitics", "futurology", "india", "singularity",
        "machinelearning", "programming", "cybersecurity",
        "spacex", "energy", "climate",
    ]
    articles: list[RawArticle] = []
    for sub in subreddits:
        try:
            resp = await client.get(
                f"https://www.reddit.com/r/{sub}/hot.json?limit=10",
                headers={**_HEADERS, "Accept": "application/json"},
                timeout=12,
            )
            resp.raise_for_status()
            data = resp.json()
            count = 0
            for post in data.get("data", {}).get("children", []):
                d = post.get("data", {})
                title = d.get("title", "").strip()
                if not title or d.get("stickied") or len(title) < 15:
                    continue
                url = d.get("url", "")
                if "reddit.com/r/" in url and "/comments/" in url:
                    url = f"https://reddit.com{d.get('permalink', '')}"
                articles.append(
                    RawArticle(
                        title=title, url=url, source=f"r/{sub}",
                        published=datetime.utcfromtimestamp(d.get("created_utc", 0)).isoformat() if d.get("created_utc") else "",
                        description=(d.get("selftext") or "")[:500],
                    )
                )
                count += 1
            logger.info("Reddit  r/%-16s → %d posts", sub, count)
        except Exception as exc:
            logger.debug("Reddit r/%s failed: %s", sub, str(exc)[:60])
    return articles


# ── Hacker News API ───────────────────────────────────────────────────────────

async def scrape_hackernews(client: httpx.AsyncClient) -> list[RawArticle]:
    articles: list[RawArticle] = []
    try:
        resp = await client.get("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10)
        resp.raise_for_status()
        story_ids = resp.json()[:25]
        tasks = [client.get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json", timeout=10) for sid in story_ids]
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
                        published=datetime.utcfromtimestamp(item.get("time", 0)).isoformat() if item.get("time") else "",
                        description=f"Score: {item.get('score', 0)} | Comments: {item.get('descendants', 0)}",
                    )
                )
            except Exception:
                continue
        logger.info("Hacker News API → %d stories", len(articles))
    except Exception as exc:
        logger.debug("HN API failed: %s", str(exc)[:60])
    return articles


# ── Google News scraping ──────────────────────────────────────────────────────

async def scrape_google_news(client: httpx.AsyncClient) -> list[RawArticle]:
    articles: list[RawArticle] = []
    MAX_PER_QUERY = 20
    try:
        resp = await client.get(
            "https://news.google.com/search",
            params={"q": "breaking news today", "hl": "en-US", "gl": "US", "ceid": "US:en"},
            headers=_HEADERS, timeout=15,
        )
        if resp.status_code != 200:
            return []
        title_pattern = re.compile(r'<a[^>]*class="[^"]*JtKRv[^"]*"[^>]*>([^<]+)</a>', re.I)
        count = 0
        for match in title_pattern.finditer(resp.text):
            if count >= MAX_PER_QUERY:
                break
            title = unescape(match.group(1).strip())
            if title and len(title) > 15:
                articles.append(RawArticle(title=title, url="https://news.google.com", source="Google News"))
                count += 1
        logger.info("Google News scrape → %d items", count)
    except Exception as exc:
        logger.debug("Google News scrape failed: %s", str(exc)[:60])
    return articles


# ── BBC / NPR / News site scraping ───────────────────────────────────────────

async def scrape_news_sites(client: httpx.AsyncClient) -> list[RawArticle]:
    articles: list[RawArticle] = []
    sites = [
        {"url": "https://www.bbc.com/news", "source": "BBC News",
         "patterns": [re.compile(r'<h2[^>]*data-testid="card-headline"[^>]*>([^<]+)</h2>', re.I),
                      re.compile(r'<h3[^>]*>([^<]{20,120})</h3>', re.I)]},
        {"url": "https://text.npr.org/", "source": "NPR",
         "patterns": [re.compile(r'<a[^>]*class="topic-title"[^>]*>\s*<h2[^>]*>([^<]+)</h2>', re.I),
                      re.compile(r'<a[^>]*href="/\d+">([^<]{20,120})</a>', re.I)]},
    ]
    for site in sites:
        try:
            resp = await client.get(site["url"], headers=_HEADERS, timeout=15, follow_redirects=True)
            if resp.status_code != 200:
                continue
            found = set()
            for pattern in site["patterns"]:
                for match in pattern.finditer(resp.text):
                    title = unescape(match.group(1).strip())
                    if title and len(title) > 15 and title not in found:
                        found.add(title)
                        articles.append(RawArticle(title=title, url=site["url"], source=site["source"]))
            logger.info("%-15s → %d headlines", site["source"], len(found))
        except Exception as exc:
            logger.debug("%s scrape failed: %s", site["source"], str(exc)[:60])
    return articles


# ── Twitter/X Trends ──────────────────────────────────────────────────────────

async def scrape_twitter_trends(client: httpx.AsyncClient) -> list[RawArticle]:
    articles: list[RawArticle] = []
    try:
        resp = await client.get("https://trends24.in/united-states/", headers=_HEADERS, timeout=15)
        if resp.status_code != 200:
            return []
        trends = set()
        for pattern in [re.compile(r'<a[^>]*>([#@]\w[\w\s]{2,30})</a>', re.I)]:
            for match in pattern.finditer(resp.text):
                trend = match.group(1).strip()
                if trend and trend.startswith("#") and len(trend) > 2:
                    trends.add(trend)
        for trend in list(trends)[:15]:
            search_query = trend.replace("#", "").replace(" ", "+")
            articles.append(RawArticle(
                title=f"Trending on X: {trend}",
                url=f"https://x.com/search?q={search_query}",
                source="Twitter/X Trends",
                description=f"Currently trending on Twitter/X: {trend}",
            ))
        if trends:
            logger.info("Twitter trends → %d topics", len(trends))
    except Exception as exc:
        logger.debug("Twitter trends failed: %s", str(exc)[:60])
    return articles


# ── Product Hunt ─────────────────────────────────────────────────────────────

async def scrape_producthunt(client: httpx.AsyncClient) -> list[RawArticle]:
    articles: list[RawArticle] = []
    try:
        resp = await client.get(
            "https://www.producthunt.com/",
            headers=_HEADERS, timeout=15,
        )
        if resp.status_code != 200:
            return []
        pattern = re.compile(r'<a[^>]*href="(/posts/[^"]+)"[^>]*>([^<]{10,100})</a>', re.I)
        seen = set()
        for match in pattern.finditer(resp.text):
            path, title = match.group(1), unescape(match.group(2).strip())
            if title and title not in seen:
                seen.add(title)
                articles.append(RawArticle(
                    title=title,
                    url=f"https://www.producthunt.com{path}",
                    source="Product Hunt",
                ))
        logger.info("Product Hunt → %d items", len(articles))
    except Exception as exc:
        logger.debug("Product Hunt failed: %s", str(exc)[:60])
    return articles


# ── Public API ────────────────────────────────────────────────────────────────

async def scrape_all() -> list[RawArticle]:
    """Run all scrapers concurrently with per-scraper timeouts."""
    async with httpx.AsyncClient(headers=_HEADERS, follow_redirects=True) as client:
        scrapers = [
            ("Reddit", scrape_reddit(client)),
            ("HN", scrape_hackernews(client)),
            ("Google News", scrape_google_news(client)),
            ("News Sites", scrape_news_sites(client)),
            ("Twitter", scrape_twitter_trends(client)),
            ("ProductHunt", scrape_producthunt(client)),
        ]

        articles: list[RawArticle] = []
        tasks = []
        names = []
        for name, coro in scrapers:
            tasks.append(asyncio.wait_for(coro, timeout=45))
            names.append(name)

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for name, result in zip(names, results):
            if isinstance(result, list):
                articles.extend(result)
            elif isinstance(result, Exception):
                logger.debug("Scraper %s timed out or failed: %s", name, str(result)[:60])

    logger.info("Scrapers total → %d raw articles", len(articles))
    return articles
