"""
Intelligence layer — uses an LLM to summarise, score, tag, and cluster articles.
Priority: Google Gemini (free) → OpenAI (paid) → heuristic fallback.
"""

import asyncio
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


# ── Shared Prompt ─────────────────────────────────────────────────────────────

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


def _build_user_message(articles: list[RawArticle]) -> str:
    numbered = "\n".join(
        f"{i+1}. [{a.source}] {a.title}"
        + (f" — {a.description[:150]}" if a.description else "")
        for i, a in enumerate(articles)
    )
    return (
        f"Analyse these {len(articles)} news articles. "
        f"Return a JSON array of {len(articles)} objects (one per article, same order).\n\n"
        f"{numbered}"
    )


def _parse_llm_response(content: str) -> list[dict]:
    """Parse LLM response, stripping markdown fences if present."""
    content = re.sub(r"^```(?:json)?\s*", "", content.strip())
    content = re.sub(r"\s*```$", "", content.strip())
    results = json.loads(content)
    if isinstance(results, dict):
        results = [results]
    return results


# ── Google Gemini (FREE) ─────────────────────────────────────────────────────

async def _gemini_analyse_batch(articles: list[RawArticle]) -> list[dict]:
    """Send a batch of articles to Google Gemini for analysis."""
    if not config.GEMINI_API_KEY:
        return []

    user_msg = _build_user_message(articles)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent",
                params={"key": config.GEMINI_API_KEY},
                json={
                    "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
                    "contents": [{"parts": [{"text": user_msg}]}],
                    "generationConfig": {"temperature": 0.2},
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["candidates"][0]["content"]["parts"][0]["text"]
            return _parse_llm_response(content)
    except Exception as exc:
        logger.warning("Gemini analysis failed: %s", exc)
        return []


# ── OpenAI-compatible (fallback) ─────────────────────────────────────────────

async def _openai_analyse_batch(articles: list[RawArticle]) -> list[dict]:
    """Send a batch of articles to an OpenAI-compatible API for analysis."""
    if not config.OPENAI_API_KEY:
        return []

    user_msg = _build_user_message(articles)

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
            return _parse_llm_response(content)
    except Exception as exc:
        logger.warning("OpenAI analysis failed: %s", exc)
        return []


# ── LLM dispatcher ───────────────────────────────────────────────────────────

async def _llm_analyse_batch(articles: list[RawArticle]) -> list[dict]:
    """Try Gemini first (free), then OpenAI, then return empty."""
    if config.GEMINI_API_KEY:
        results = await _gemini_analyse_batch(articles)
        if results:
            return results

    if config.OPENAI_API_KEY:
        results = await _openai_analyse_batch(articles)
        if results:
            return results

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

def _get_llm_name() -> str:
    if config.GEMINI_API_KEY:
        return f"Gemini ({config.GEMINI_MODEL})"
    if config.OPENAI_API_KEY:
        return f"OpenAI ({config.OPENAI_MODEL})"
    return "heuristic"


async def analyse(articles: list[RawArticle]) -> list[AnalysedArticle]:
    """Analyse a batch of articles. Uses LLM if available, else heuristics."""
    if not articles:
        return []

    has_llm = config.GEMINI_API_KEY or config.OPENAI_API_KEY

    # Step 1: Score ALL articles with fast heuristics first
    heuristic_results = [_heuristic_score(a) for a in articles]

    if not has_llm:
        logger.info("No LLM API key set — using heuristic scoring")
        all_results = heuristic_results
    else:
        # Step 2: Only send the top-scoring articles to the LLM (saves quota)
        MAX_LLM_ARTICLES = 50
        scored = sorted(
            enumerate(articles),
            key=lambda x: heuristic_results[x[0]].get("priority", 0),
            reverse=True,
        )
        llm_indices = [idx for idx, _ in scored[:MAX_LLM_ARTICLES]]
        llm_articles = [articles[idx] for idx in llm_indices]

        logger.info(
            "Sending top %d/%d articles to LLM (%s)",
            len(llm_articles),
            len(articles),
            _get_llm_name(),
        )

        # Step 3: Process in batches with rate-limiting (Gemini free = 15 RPM)
        BATCH_SIZE = 10
        llm_results_map: dict[int, dict] = {}

        for batch_num, i in enumerate(range(0, len(llm_articles), BATCH_SIZE)):
            if batch_num > 0:
                # Wait 5s between batches to stay under 15 RPM
                await asyncio.sleep(5)

            batch = llm_articles[i : i + BATCH_SIZE]
            batch_indices = llm_indices[i : i + BATCH_SIZE]
            llm_results = await _llm_analyse_batch(batch)

            if len(llm_results) == len(batch):
                for idx, result in zip(batch_indices, llm_results):
                    llm_results_map[idx] = result
            else:
                logger.warning(
                    "LLM returned %d results for %d articles, using heuristics",
                    len(llm_results),
                    len(batch),
                )

        # Step 4: Merge — use LLM results where available, heuristics for rest
        all_results = []
        for i in range(len(articles)):
            if i in llm_results_map:
                all_results.append(llm_results_map[i])
            else:
                all_results.append(heuristic_results[i])

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
