"""
Intelligence layer — uses an LLM to summarise, score, tag, and cluster articles.
Falls back to heuristic scoring when no API key is set.
"""

import json
import logging
import re
from dataclasses import dataclass

import httpx

import config
from fetcher import RawArticle

logger = logging.getLogger(__name__)


@dataclass
class AnalysedArticle:
    title: str
    url: str
    source: str
    published: str
    hash: str
    summary: str
    tags: list[str]
    priority: int  # 0–100
    cluster_id: str


# ── LLM Analysis ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a breaking-news analyst. For each article, return JSON (no markdown):
{
  "summary": "<one-line breaking-news style summary, max 120 chars>",
  "tags": ["<topic1>", "<topic2>"],
  "priority": <0-100 int>,
  "cluster": "<short cluster label for grouping similar stories>"
}
Priority scoring guide:
- 90-100: Major global event, market crash, war, assassination
- 70-89:  Significant tech/business news (big acquisition, major product launch)
- 50-69:  Notable news (funding rounds, policy changes, important reports)
- 30-49:  Interesting but not urgent
- 0-29:   Routine updates, minor news
"""


async def _llm_analyse_batch(articles: list[RawArticle]) -> list[dict]:
    """Send a batch of articles to the LLM for analysis."""
    if not config.OPENAI_API_KEY:
        return []

    numbered = "\n".join(
        f"{i+1}. [{a.source}] {a.title}"
        + (f" — {a.description[:150]}" if a.description else "")
        for i, a in enumerate(articles)
    )
    user_msg = (
        f"Analyse these {len(articles)} news articles. "
        f"Return a JSON array of {len(articles)} objects (one per article, same order).\n\n"
        f"{numbered}"
    )

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{config.OPENAI_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                json={
                    "model": config.OPENAI_MODEL,
                    "temperature": 0.2,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                },
                timeout=60,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]

            # Strip markdown code fences if present
            content = re.sub(r"^```(?:json)?\s*", "", content.strip())
            content = re.sub(r"\s*```$", "", content.strip())

            results = json.loads(content)
            if isinstance(results, dict):
                results = [results]
            return results
    except Exception as exc:
        logger.warning("LLM analysis failed: %s", exc)
        return []


# ── Heuristic Fallback ───────────────────────────────────────────────────────

def _heuristic_score(article: RawArticle) -> dict:
    """Fast keyword-based scoring when LLM is unavailable."""
    text = f"{article.title} {article.description}".lower()
    score = 30  # baseline

    # Urgency signals
    urgent_words = ["breaking", "urgent", "just in", "alert", "crash", "war", "killed"]
    for w in urgent_words:
        if w in text:
            score += 25
            break

    # Keyword boost
    for kw in config.PRIORITY_KEYWORDS:
        if kw.lower() in text:
            score += 10
            break

    # Market words
    market_words = ["ipo", "acquisition", "billion", "funding", "valuation", "merger"]
    for w in market_words:
        if w in text:
            score += 10
            break

    score = min(score, 100)

    # Simple tag extraction
    tags = []
    tag_map = {
        "ai": ["ai", "artificial intelligence", "machine learning", "gpt", "llm"],
        "finance": ["stock", "market", "ipo", "funding", "billion", "valuation"],
        "startups": ["startup", "founder", "seed", "series a", "y combinator"],
        "geopolitics": ["war", "sanction", "treaty", "nato", "china", "russia"],
        "tech": ["google", "apple", "microsoft", "meta", "amazon", "openai"],
    }
    for tag, keywords in tag_map.items():
        if any(k in text for k in keywords):
            tags.append(tag)
    if not tags:
        tags = ["general"]

    return {
        "summary": article.title[:120],
        "tags": tags,
        "priority": score,
        "cluster": tags[0],
    }


# ── Filtering ─────────────────────────────────────────────────────────────────

def _passes_filters(article: RawArticle, analysis: dict) -> bool:
    """Check if article passes user-defined keyword filters."""
    if not config.FILTER_KEYWORDS:
        return True
    text = f"{article.title} {article.description} {analysis.get('summary', '')}".lower()
    return any(kw.lower() in text for kw in config.FILTER_KEYWORDS)


# ── Public API ────────────────────────────────────────────────────────────────

async def analyse(articles: list[RawArticle]) -> list[AnalysedArticle]:
    """Analyse a batch of articles. Uses LLM if available, else heuristics."""
    if not articles:
        return []

    # Process in batches of 15 for the LLM
    BATCH_SIZE = 15
    all_results: list[dict] = []

    if config.OPENAI_API_KEY:
        for i in range(0, len(articles), BATCH_SIZE):
            batch = articles[i : i + BATCH_SIZE]
            llm_results = await _llm_analyse_batch(batch)
            if len(llm_results) == len(batch):
                all_results.extend(llm_results)
            else:
                # Fallback for this batch
                logger.warning(
                    "LLM returned %d results for %d articles, using heuristics",
                    len(llm_results),
                    len(batch),
                )
                all_results.extend(_heuristic_score(a) for a in batch)
    else:
        logger.info("No OPENAI_API_KEY set — using heuristic scoring")
        all_results = [_heuristic_score(a) for a in articles]

    # Build AnalysedArticle objects and apply filters
    analysed: list[AnalysedArticle] = []
    for article, result in zip(articles, all_results):
        if not _passes_filters(article, result):
            continue

        priority = int(result.get("priority", 30))

        # Keyword boost on top of LLM score
        text_lower = f"{article.title} {article.description}".lower()
        for kw in config.PRIORITY_KEYWORDS:
            if kw.lower() in text_lower:
                priority = min(priority + 10, 100)
                break

        if priority < config.MIN_PRIORITY_SCORE:
            continue

        tags = result.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]

        analysed.append(
            AnalysedArticle(
                title=article.title,
                url=article.url,
                source=article.source,
                published=article.published,
                hash=article.hash,
                summary=result.get("summary", article.title[:120]),
                tags=tags,
                priority=priority,
                cluster_id=result.get("cluster", ""),
            )
        )

    # Sort by priority descending
    analysed.sort(key=lambda a: a.priority, reverse=True)
    logger.info("Analysis complete: %d articles passed filters", len(analysed))
    return analysed
