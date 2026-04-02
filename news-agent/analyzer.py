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

def _make_summary(title: str, description: str) -> str:
    """Generate a concise summary from title + description without LLM."""
    title = title.strip()
    desc = description.strip()

    # If description adds real info beyond the title, combine them
    if desc and len(desc) > 30:
        # Remove common prefixes/suffixes from descriptions
        for noise in ["Continue reading...", "Read more", "Click here", "...", "---"]:
            desc = desc.replace(noise, "").strip()
        # If desc is just the title repeated, skip it
        if desc.lower()[:40] != title.lower()[:40] and len(desc) > 20:
            # Take first sentence of description
            first_sentence = desc.split(". ")[0].split(".\n")[0]
            if len(first_sentence) > 20 and len(first_sentence) < 200:
                return first_sentence[:120]

    # Clean up title as summary
    summary = title
    # Remove source suffixes like "- Reuters", "| BBC"
    for sep in [" - ", " | ", " — ", " · "]:
        if sep in summary:
            parts = summary.split(sep)
            # Keep the longer part (usually the actual headline)
            summary = max(parts[:-1], key=len) if len(parts) > 1 else parts[0]
    return summary[:120]


# Words that indicate junk / non-news content
_JUNK_PATTERNS = [
    "livestream", "live stream", "watch here", "watch live",
    "weather forecast", "weather today", "weather |",
    "horoscope", "crossword", "sudoku", "quiz:",
    "recap:", "roundup:", "newsletter", "subscribe",
    "nfl draft", "nfl free agency", "fantasy football",
    "transfer news", "transfer rumours", "transfer centre",
    "odds and predictions", "betting", "sportsbook",
]


def _heuristic_score(article: RawArticle) -> dict:
    """Smart keyword-based scoring — works great without any LLM."""
    title = article.title
    text = f"{title} {article.description}".lower()
    score = 0

    # ── Junk filter: penalise non-news content ──
    for junk in _JUNK_PATTERNS:
        if junk in text:
            score -= 50
            break

    # ── Source quality bonus ──
    high_quality = ["techcrunch", "reuters", "bbc", "ars technica",
                    "hacker news", "economic times", "al jazeera"]
    source_lower = article.source.lower()
    if any(s in source_lower for s in high_quality):
        score += 15
    elif "google news" in source_lower:
        score += 5  # lower because scraping pulls junk
    elif source_lower.startswith("r/"):
        score += 10

    # ── Urgency signals (strong) ──
    urgency_high = ["breaking:", "just in:", "urgent:", "developing:"]
    for w in urgency_high:
        if w in text:
            score += 30
            break

    urgency_medium = ["breaking news", "breaking -", "just announced",
                      "confirms", "revealed", "emergency", "earthquake",
                      "tsunami", "explosion", "assassination", "coup"]
    for w in urgency_medium:
        if w in text:
            score += 20
            break

    # ── Market impact signals ──
    market_high = ["ipo", "acquisition", "acquires", "merger", "buys for",
                   "raises $", "billion", "trillion", "market crash",
                   "stock plunge", "stock surge"]
    for w in market_high:
        if w in text:
            score += 25
            break

    market_medium = ["funding", "valuation", "layoffs", "lays off",
                     "cuts jobs", "files for", "goes public", "stock market",
                     "oil price", "interest rate", "tariff"]
    for w in market_medium:
        if w in text:
            score += 15
            break

    # ── User keyword boost ──
    keyword_hits = 0
    for kw in config.PRIORITY_KEYWORDS:
        if kw.lower() in text:
            keyword_hits += 1
    score += min(keyword_hits * 8, 24)  # up to 24 points for 3+ keywords

    # ── Virality signals ──
    viral_words = ["shocking", "massive", "historic", "unprecedented",
                   "first ever", "record-breaking", "millions"]
    for w in viral_words:
        if w in text:
            score += 10
            break

    # ── Tech/AI signals (since user cares about these) ──
    tech_signals = ["openai", "chatgpt", "claude", "gemini", "gpt-",
                    "llm", "artificial intelligence", "neural",
                    "robot", "autonomous", "quantum"]
    tech_hits = sum(1 for w in tech_signals if w in text)
    if tech_hits:
        score += 10 + (tech_hits * 3)

    # ── Normalise to 0–100 ──
    score = max(0, min(100, score + 25))  # +25 baseline

    # ── Tag extraction (richer) ──
    tags = []
    tag_map = {
        "ai": ["ai ", " ai,", "artificial intelligence", "machine learning",
               "gpt", "llm", "chatgpt", "openai", "claude", "gemini",
               "deep learning", "neural net", "robot"],
        "finance": ["stock", "market", "ipo", "funding", "billion",
                     "valuation", "investor", "revenue", "profit",
                     "oil price", "interest rate", "inflation", "economy"],
        "startups": ["startup", "founder", "seed round", "series a",
                     "series b", "y combinator", "yc ", "venture",
                     "accelerator", "incubator"],
        "geopolitics": ["war ", "sanction", "treaty", "nato", "iran",
                        "china", "russia", "ukraine", "missile",
                        "military", "troops", "diplomat"],
        "tech": ["google", "apple", "microsoft", "meta ", "amazon",
                 "nvidia", "tesla", "spacex", "samsung", "intel"],
        "security": ["hack", "breach", "cyber", "vulnerability",
                     "malware", "ransomware", "data leak"],
        "science": ["nasa", "artemis", "space", "quantum", "research",
                    "discovery", "study finds", "scientists"],
        "india": ["india", "modi", "rupee", "sensex", "nifty",
                  "mumbai", "delhi", "bengaluru", "kerala"],
        "crypto": ["bitcoin", "ethereum", "crypto", "blockchain",
                   "defi", "nft", "web3"],
    }
    for tag, keywords in tag_map.items():
        if any(k in text for k in keywords):
            tags.append(tag)
    if not tags:
        tags = ["general"]

    # ── Cluster by primary tag ──
    cluster = tags[0]

    # ── Generate summary ──
    summary = _make_summary(title, article.description)

    return {
        "summary": summary,
        "tags": tags,
        "priority": score,
        "cluster": cluster,
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
