"""
Intelligence layer — uses an LLM to summarise, score, tag, and cluster articles.
Priority: Google Gemini (free) → OpenAI (paid) → smart heuristic fallback.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from html import unescape

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


# ── Shared LLM Prompt ────────────────────────────────────────────────────────

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
        f"{i+1}. [{a.source}] {a.title}" + (f" — {a.description[:150]}" if a.description else "")
        for i, a in enumerate(articles)
    )
    return f"Analyse these {len(articles)} news articles. Return a JSON array of {len(articles)} objects.\n\n{numbered}"


def _parse_llm_response(content: str) -> list[dict]:
    content = re.sub(r"^```(?:json)?\s*", "", content.strip())
    content = re.sub(r"\s*```$", "", content.strip())
    results = json.loads(content)
    if isinstance(results, dict):
        results = [results]
    return results


# ── Gemini ────────────────────────────────────────────────────────────────────

async def _gemini_analyse_batch(articles: list[RawArticle]) -> list[dict]:
    if not config.GEMINI_API_KEY:
        return []
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent",
                params={"key": config.GEMINI_API_KEY},
                json={"system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
                      "contents": [{"parts": [{"text": _build_user_message(articles)}]}],
                      "generationConfig": {"temperature": 0.2}},
                timeout=60,
            )
            resp.raise_for_status()
            content = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            return _parse_llm_response(content)
    except Exception as exc:
        logger.warning("Gemini failed: %s", str(exc)[:80])
        return []


# ── OpenAI ────────────────────────────────────────────────────────────────────

async def _openai_analyse_batch(articles: list[RawArticle]) -> list[dict]:
    if not config.OPENAI_API_KEY:
        return []
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{config.OPENAI_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                json={"model": config.OPENAI_MODEL, "temperature": 0.2,
                      "messages": [{"role": "system", "content": _SYSTEM_PROMPT},
                                   {"role": "user", "content": _build_user_message(articles)}]},
                timeout=60,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return _parse_llm_response(content)
    except Exception as exc:
        logger.warning("OpenAI failed: %s", str(exc)[:80])
        return []


async def _llm_analyse_batch(articles: list[RawArticle]) -> list[dict]:
    if config.GEMINI_API_KEY:
        results = await _gemini_analyse_batch(articles)
        if results:
            return results
    if config.OPENAI_API_KEY:
        results = await _openai_analyse_batch(articles)
        if results:
            return results
    return []


# ── Smart Heuristic Scoring ──────────────────────────────────────────────────

_JUNK_PATTERNS = [
    "livestream", "live stream", "watch here", "watch live",
    "weather forecast", "weather today", "weather |",
    "horoscope", "crossword", "sudoku", "quiz:",
    "nfl draft", "nfl free agency", "fantasy football",
    "transfer news", "transfer rumours", "transfer centre",
    "odds and predictions", "betting", "sportsbook",
    "daily briefing", "podcast", "opinion:", "editorial:",
    "sponsored", "promoted", "advertisement", "photo gallery",
    "video:", "best deals", "how to ",
]

_CLICKBAIT = ["you won't believe", "this is why", "here's why", "what happened next"]


def _make_summary(title: str, description: str) -> str:
    title = unescape(title).strip()
    desc = unescape(description).strip()
    # Clean source suffixes
    for sep in [" - ", " | ", " — ", " · "]:
        if sep in title:
            parts = title.split(sep)
            title = max(parts[:-1], key=len) if len(parts) > 1 else parts[0]

    if desc and len(desc) > 30:
        for noise in ["Continue reading...", "Read more", "Click here", "...", "---"]:
            desc = desc.replace(noise, "").strip()
        if desc.lower()[:40] != title.lower()[:40] and len(desc) > 20:
            first_sentence = desc.split(". ")[0].split(".\n")[0]
            if 20 < len(first_sentence) < 200:
                return first_sentence[:120]
    return title[:120]


def _heuristic_score(article: RawArticle) -> dict:
    title = article.title
    text = f"{title} {article.description}".lower()
    score = 0

    # Junk filter
    for junk in _JUNK_PATTERNS:
        if junk in text:
            score -= 50
            break

    # Clickbait penalty
    for bait in _CLICKBAIT:
        if bait in text:
            score -= 10
            break
    if title.endswith("?") and len(title) < 50:
        score -= 5

    # Source quality
    source_lower = article.source.lower()
    high_quality = ["techcrunch", "reuters", "bbc", "ars technica", "hacker news",
                    "economic times", "al jazeera", "the verge", "wired", "cnbc",
                    "guardian", "cnn", "indian express", "times of india", "npr"]
    if any(s in source_lower for s in high_quality):
        score += 15
    elif "google news" in source_lower:
        score += 5
    elif source_lower.startswith("r/"):
        score += 10

    # Urgency (strong)
    for w in ["breaking:", "just in:", "urgent:", "developing:"]:
        if w in text:
            score += 30
            break

    # Urgency (medium)
    for w in ["breaking news", "just announced", "confirms", "revealed", "emergency",
              "earthquake", "tsunami", "explosion", "assassination", "coup"]:
        if w in text:
            score += 20
            break

    # Market impact (high)
    for w in ["ipo", "acquisition", "acquires", "merger", "buys for",
              "raises $", "billion", "trillion", "market crash", "stock plunge", "stock surge"]:
        if w in text:
            score += 25
            break

    # Market impact (medium)
    for w in ["funding", "valuation", "layoffs", "lays off", "cuts jobs",
              "files for", "goes public", "stock market", "oil price",
              "interest rate", "tariff", "sanctions"]:
        if w in text:
            score += 15
            break

    # User keyword boost
    keyword_hits = sum(1 for kw in config.PRIORITY_KEYWORDS if kw.lower() in text)
    score += min(keyword_hits * 8, 32)

    # Virality
    for w in ["shocking", "massive", "historic", "unprecedented", "first ever",
              "record-breaking", "millions", "exclusive"]:
        if w in text:
            score += 10
            break

    # Tech/AI signals
    tech_signals = ["openai", "chatgpt", "claude", "gemini", "gpt-", "llm",
                    "artificial intelligence", "neural", "robot", "autonomous", "quantum"]
    tech_hits = sum(1 for w in tech_signals if w in text)
    if tech_hits:
        score += 10 + (tech_hits * 3)

    # Description quality bonus
    if len(article.description) > 100:
        for verb in ["announces", "launches", "confirms", "reveals", "acquires", "raises"]:
            if verb in article.description.lower():
                score += 5
                break

    # Normalise to 0–100
    score = max(0, min(100, score + 25))

    # Tags
    tags = []
    tag_map = {
        "ai": ["ai ", " ai,", "artificial intelligence", "machine learning", "gpt", "llm",
               "chatgpt", "openai", "claude", "gemini", "deep learning", "neural net", "robot"],
        "finance": ["stock", "market", "ipo", "funding", "billion", "valuation", "investor",
                     "revenue", "profit", "oil price", "interest rate", "inflation", "economy"],
        "startups": ["startup", "founder", "seed round", "series a", "series b",
                     "y combinator", "yc ", "venture", "accelerator"],
        "geopolitics": ["war ", "sanction", "treaty", "nato", "iran", "china", "russia",
                        "ukraine", "missile", "military", "troops", "diplomat"],
        "tech": ["google", "apple", "microsoft", "meta ", "amazon", "nvidia", "tesla",
                 "spacex", "samsung", "intel"],
        "security": ["hack", "breach", "cyber", "vulnerability", "malware", "ransomware", "data leak"],
        "science": ["nasa", "artemis", "space", "quantum", "research", "discovery", "study finds", "scientists"],
        "india": ["india", "modi", "rupee", "sensex", "nifty", "mumbai", "delhi", "bengaluru", "kerala"],
        "crypto": ["bitcoin", "ethereum", "crypto", "blockchain", "defi", "nft", "web3"],
        "health": ["covid", "pandemic", "vaccine", "who ", "fda", "disease", "hospital", "drug"],
        "climate": ["climate", "carbon", "emissions", "renewable", "solar", "wind energy"],
        "legal": ["supreme court", "lawsuit", "ruling", "verdict", "indictment", "sentenced"],
    }
    for tag, keywords in tag_map.items():
        if any(k in text for k in keywords):
            tags.append(tag)
    if not tags:
        tags = ["general"]

    return {
        "summary": _make_summary(title, article.description),
        "tags": tags,
        "priority": score,
        "cluster": tags[0],
    }


# ── Filtering ─────────────────────────────────────────────────────────────────

def _passes_filters(article: RawArticle, analysis: dict) -> bool:
    if not config.FILTER_KEYWORDS:
        return True
    text = f"{article.title} {article.description} {analysis.get('summary', '')}".lower()
    return any(kw.lower() in text for kw in config.FILTER_KEYWORDS)


# ── Public API ────────────────────────────────────────────────────────────────

async def analyse(articles: list[RawArticle]) -> list[AnalysedArticle]:
    if not articles:
        return []

    has_llm = config.GEMINI_API_KEY or config.OPENAI_API_KEY

    # Step 1: Heuristic score everything
    heuristic_results = [_heuristic_score(a) for a in articles]

    if not has_llm:
        logger.info("No LLM key — using heuristic scoring for %d articles", len(articles))
        all_results = heuristic_results
    else:
        # Step 2: Send top 50 to LLM
        MAX_LLM = 50
        scored = sorted(enumerate(articles), key=lambda x: heuristic_results[x[0]].get("priority", 0), reverse=True)
        llm_indices = [idx for idx, _ in scored[:MAX_LLM]]
        llm_articles = [articles[idx] for idx in llm_indices]
        logger.info("Sending top %d/%d to LLM", len(llm_articles), len(articles))

        BATCH_SIZE = 10
        llm_map: dict[int, dict] = {}
        for batch_num, i in enumerate(range(0, len(llm_articles), BATCH_SIZE)):
            if batch_num > 0:
                await asyncio.sleep(5)
            batch = llm_articles[i:i + BATCH_SIZE]
            batch_indices = llm_indices[i:i + BATCH_SIZE]
            llm_results = await _llm_analyse_batch(batch)
            if len(llm_results) == len(batch):
                for idx, result in zip(batch_indices, llm_results):
                    llm_map[idx] = result
            else:
                logger.warning("LLM returned %d/%d, using heuristics", len(llm_results), len(batch))

        all_results = [llm_map.get(i, heuristic_results[i]) for i in range(len(articles))]

    # Build output
    analysed: list[AnalysedArticle] = []
    for article, result in zip(articles, all_results):
        if not _passes_filters(article, result):
            continue

        priority = int(result.get("priority", 30))
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

        analysed.append(AnalysedArticle(
            title=unescape(article.title),
            url=article.url,
            source=article.source,
            published=article.published,
            hash=article.hash,
            summary=unescape(result.get("summary", article.title[:120])),
            tags=tags,
            priority=priority,
            cluster_id=result.get("cluster", ""),
        ))

    analysed.sort(key=lambda a: a.priority, reverse=True)
    logger.info("Analysis: %d articles passed filters (min score %d)", len(analysed), config.MIN_PRIORITY_SCORE)
    return analysed
