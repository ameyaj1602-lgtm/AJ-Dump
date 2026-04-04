"""
Intelligence layer — uses an LLM to summarise, score, tag, and cluster articles.
Priority: Google Gemini (free) → OpenAI (paid) → smart heuristic fallback.

v2: Improved quality — stronger junk filter, source tiers, freshness boost,
    title quality checks, duplicate pattern detection, category-aware scoring.
"""

import asyncio
import json
import logging
import math
import re
from collections import Counter, defaultdict
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


# ── Smart Heuristic Scoring (v2 — much stricter) ───────────────────────────

# Hard-kill: these get score = 0 instantly
_KILL_PATTERNS = [
    "horoscope", "crossword", "sudoku", "quiz:", "wordle",
    "best deals", "coupon", "promo code", "discount code",
    "sponsored", "promoted", "advertisement", "advertorial",
    "photo gallery", "in pictures", "pictures of the week",
    "recipe:", "recipes for", "cooking tips",
    "daily briefing", "morning briefing", "evening briefing",
    "newsletter signup", "subscribe now",
    "celebrity", "kardashian", "bachelor", "bachelorette",
    "box office", "movie review", "tv recap", "season finale",
    "fashion week", "red carpet", "outfit",
    "lottery", "sweepstakes", "giveaway",
    "astrology", "zodiac", "tarot",
]

# Strong penalty: -40
_JUNK_PATTERNS = [
    "livestream", "live stream", "watch here", "watch live", "live updates",
    "weather forecast", "weather today", "weather |", "weather alert",
    "nfl draft", "nfl free agency", "fantasy football", "fantasy sports",
    "transfer news", "transfer rumours", "transfer centre", "transfer window",
    "odds and predictions", "betting", "sportsbook", "parlay",
    "podcast:", "podcast episode", "listen to", "watch:",
    "opinion:", "editorial:", "op-ed:", "letter to the editor",
    "obituary", "death notice",
    "video:", "slideshow", "photos:", "gallery:",
    "how to ", "tips for ", "ways to ", "guide to ",
    "review:", "hands-on:", "unboxing",
    "best of", "top 10", "top 5", "ranked:",
]

# Clickbait: -15
_CLICKBAIT = [
    "you won't believe", "this is why", "here's why", "what happened next",
    "shocked everyone", "the truth about", "you need to know",
    "is it worth", "we tried", "i tried", "we tested",
    "everything you need to know", "explained:", "what is",
]

# Low-value repetitive patterns: -20
_LOW_VALUE = [
    "stock price today", "share price", "stock to buy",
    "ipl ", "ipl:", "cricket score", "match preview", "match prediction",
    "daily digest", "morning news", "evening news",
    "what's new in", "what's coming",
    "trending on x:", "trending on twitter",
    "meme", "viral video", "tiktok",
    "deals roundup", "sale alert", "price drop",
]

# Source quality tiers (aggressive — tier1 gets massive boost)
_TIER1_SOURCES = [
    "reuters", "bbc", "al jazeera", "guardian", "financial times",
    "wall street journal", "new york times", "washington post",
    "economist", "bloomberg", "associated press", "afp",
]
_TIER2_SOURCES = [
    "techcrunch", "ars technica", "the verge", "wired", "cnbc",
    "hacker news", "economic times", "indian express", "times of india",
    "cnn", "npr", "livemint", "moneycontrol", "the hindu",
    "venturebeat", "zdnet", "science daily", "phys.org",
]
_TIER3_NOISE = [
    "trends24", "twitter/x trends", "product hunt",
]


def _title_quality_score(title: str) -> int:
    """Penalise low-quality titles."""
    score = 0
    # Too short = probably garbage
    if len(title) < 25:
        score -= 15
    # ALL CAPS = clickbait
    if title.isupper() and len(title) > 20:
        score -= 10
    # Ends with "?" and short = clickbait
    if title.endswith("?") and len(title) < 50:
        score -= 8
    # Starts with number list = listicle
    if re.match(r"^\d+\s+(best|top|ways|things|reasons|tips)", title.lower()):
        score -= 20
    # Has actual substance indicators
    if any(w in title.lower() for w in ["announces", "launches", "acquires", "raises", "reports", "confirms", "reveals"]):
        score += 8
    return score


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

    # ── HARD KILL ──
    for kill in _KILL_PATTERNS:
        if kill in text:
            return {"summary": _make_summary(title, article.description),
                    "tags": ["junk"], "priority": 0, "cluster": "junk"}

    # ── Junk filter (-40) ──
    for junk in _JUNK_PATTERNS:
        if junk in text:
            score -= 40
            break

    # ── Clickbait penalty (-15) ──
    for bait in _CLICKBAIT:
        if bait in text:
            score -= 15
            break

    # ── Low-value patterns (-20) ──
    for low in _LOW_VALUE:
        if low in text:
            score -= 20
            break

    # ── Title quality ──
    score += _title_quality_score(title)

    # ── Source quality (tiered — heavily rewards quality journalism) ──
    source_lower = article.source.lower()
    if any(s in source_lower for s in _TIER1_SOURCES):
        score += 30
    elif any(s in source_lower for s in _TIER2_SOURCES):
        score += 18
    elif source_lower.startswith("r/"):
        score += 8
    elif "google news" in source_lower:
        score += 5
    elif any(s in source_lower for s in _TIER3_NOISE):
        score -= 15

    # ── URGENCY (strong — +30) ──
    for w in ["breaking:", "just in:", "urgent:", "developing:", "alert:"]:
        if w in text:
            score += 30
            break

    # ── URGENCY (medium — +20) ──
    urgency_medium = [
        "breaking news", "just announced", "confirms", "revealed",
        "emergency", "earthquake", "tsunami", "explosion",
        "assassination", "coup", "declares war", "invaded",
        "mass shooting", "terrorist", "nuclear",
    ]
    for w in urgency_medium:
        if w in text:
            score += 20
            break

    # ── MARKET IMPACT (high — +25) ──
    market_high = [
        "ipo", "acquisition", "acquires", "merger", "buys for",
        "raises $", "billion", "trillion", "market crash",
        "stock plunge", "stock surge", "recession",
    ]
    for w in market_high:
        if w in text:
            score += 25
            break

    # ── MARKET IMPACT (medium — +15) ──
    market_med = [
        "funding", "valuation", "layoffs", "lays off", "cuts jobs",
        "files for", "goes public", "stock market", "oil price",
        "interest rate", "tariff", "sanctions", "trade war",
        "inflation", "gdp ", "rbi ", "fed ",
    ]
    for w in market_med:
        if w in text:
            score += 15
            break

    # ── User keyword boost (capped) ──
    keyword_hits = sum(1 for kw in config.PRIORITY_KEYWORDS if kw.lower() in text)
    score += min(keyword_hits * 8, 32)

    # ── VIRALITY / IMPACT ──
    impact_words = [
        "historic", "unprecedented", "first ever", "record-breaking",
        "millions", "exclusive", "leaked", "whistleblower",
        "major update", "game changer",
    ]
    for w in impact_words:
        if w in text:
            score += 12
            break

    # ── TECH/AI signals (stacked) ──
    tech_signals = [
        "openai", "chatgpt", "claude", "gemini", "gpt-", "llm",
        "artificial intelligence", "neural", "autonomous", "quantum",
        "anthropic", "meta ai", "deepmind", "midjourney", "stable diffusion",
        "apple intelligence", "copilot",
    ]
    tech_hits = sum(1 for w in tech_signals if w in text)
    if tech_hits:
        score += 10 + (tech_hits * 5)

    # ── INDIA BUSINESS signals ──
    india_biz = [
        "sensex", "nifty", "bse", "nse", "sebi", "rbi",
        "mukesh ambani", "adani", "tata", "infosys", "wipro", "reliance",
        "zomato", "swiggy", "flipkart", "paytm", "razorpay",
        "unicorn", "indian startup", "india gdp",
    ]
    india_hits = sum(1 for w in india_biz if w in text)
    if india_hits:
        score += 8 + (india_hits * 4)

    # ── GEOPOLITICS boost ──
    geo_words = [
        "nato", "un security council", "g20", "g7",
        "china taiwan", "russia ukraine", "israel",
        "nuclear deal", "peace deal", "ceasefire",
        "trade agreement", "summit",
    ]
    for w in geo_words:
        if w in text:
            score += 15
            break

    # ── Description quality bonus ──
    if len(article.description) > 100:
        for verb in ["announces", "launches", "confirms", "reveals", "acquires", "raises", "reports"]:
            if verb in article.description.lower():
                score += 5
                break

    # ── URL quality bonus ──
    url = article.url.lower()
    if url and not any(generic in url for generic in ["google.com", "reddit.com", "trends24"]):
        score += 3  # has a real source link

    # Normalise to 0–100
    score = max(0, min(100, score + 25))

    # ── Tags ──
    tags = []
    tag_map = {
        "ai": ["ai ", " ai,", "artificial intelligence", "machine learning", "gpt", "llm",
               "chatgpt", "openai", "claude", "gemini", "deep learning", "neural net",
               "anthropic", "midjourney", "copilot", "deepmind"],
        "finance": ["stock", "market", "ipo", "funding", "billion", "valuation", "investor",
                     "revenue", "profit", "oil price", "interest rate", "inflation", "economy",
                     "sensex", "nifty", "rbi", "fed ", "gdp"],
        "startups": ["startup", "founder", "seed round", "series a", "series b",
                     "y combinator", "yc ", "venture", "accelerator", "unicorn"],
        "geopolitics": ["war ", "sanction", "treaty", "nato", "iran", "china", "russia",
                        "ukraine", "missile", "military", "troops", "diplomat", "g20", "g7"],
        "tech": ["google", "apple", "microsoft", "meta ", "amazon", "nvidia", "tesla",
                 "spacex", "samsung", "intel", "tsmc", "qualcomm"],
        "security": ["hack", "breach", "cyber", "vulnerability", "malware", "ransomware",
                     "data leak", "zero day", "exploit"],
        "science": ["nasa", "artemis", "space", "quantum", "research", "discovery",
                    "study finds", "scientists", "mars", "cern"],
        "india": ["india", "modi", "rupee", "sensex", "nifty", "mumbai", "delhi",
                  "bengaluru", "kerala", "sebi", "adani", "ambani", "tata"],
        "crypto": ["bitcoin", "ethereum", "crypto", "blockchain", "defi", "nft", "web3", "solana"],
        "health": ["covid", "pandemic", "vaccine", "who ", "fda", "disease", "hospital", "drug"],
        "climate": ["climate", "carbon", "emissions", "renewable", "solar", "wind energy", "ev "],
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


# ── Filtering ─────────────────────────────────────────────────────────────

def _passes_filters(article: RawArticle, analysis: dict) -> bool:
    if not config.FILTER_KEYWORDS:
        return True
    text = f"{article.title} {article.description} {analysis.get('summary', '')}".lower()
    return any(kw.lower() in text for kw in config.FILTER_KEYWORDS)


# ── TF-IDF Clustering (zero dependencies) ───────────────────────────────────

_STOP_WORDS = frozenset([
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "each", "every", "both", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so",
    "than", "too", "very", "and", "but", "or", "if", "while", "about",
    "up", "out", "off", "over", "its", "it", "this", "that", "these",
    "those", "what", "which", "who", "whom", "new", "says", "said",
    "also", "just", "like", "get", "gets", "got", "one", "two", "first",
])


def _tokenize(text: str) -> list[str]:
    words = re.findall(r'[a-z]{2,}', text.lower())
    return [w for w in words if w not in _STOP_WORDS]


def _cluster_articles(articles: list['AnalysedArticle'], threshold: float = 0.30) -> list['AnalysedArticle']:
    """Cluster articles using TF-IDF cosine similarity. Assigns cluster_id to each."""
    if len(articles) < 2:
        return articles

    # Tokenize all articles
    docs = [_tokenize(f"{a.title} {a.summary}") for a in articles]

    # Build IDF
    doc_count = len(docs)
    df: Counter = Counter()
    for doc in docs:
        for word in set(doc):
            df[word] += 1
    idf = {word: math.log(doc_count / count) for word, count in df.items()}

    # Build TF-IDF vectors
    vectors: list[dict[str, float]] = []
    for doc in docs:
        tf = Counter(doc)
        total = len(doc) or 1
        vec = {w: (c / total) * idf.get(w, 0) for w, c in tf.items()}
        vectors.append(vec)

    def _cosine(a: dict, b: dict) -> float:
        keys = set(a) & set(b)
        if not keys:
            return 0.0
        dot = sum(a[k] * b[k] for k in keys)
        mag_a = math.sqrt(sum(v * v for v in a.values()))
        mag_b = math.sqrt(sum(v * v for v in b.values()))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    # Greedy clustering — assign each article to existing cluster or create new
    cluster_map: list[int] = [-1] * len(articles)
    cluster_reps: list[int] = []  # index of representative article per cluster
    cluster_labels: list[str] = []

    for i in range(len(articles)):
        best_cluster = -1
        best_sim = threshold
        for ci, rep in enumerate(cluster_reps):
            sim = _cosine(vectors[i], vectors[rep])
            if sim > best_sim:
                best_sim = sim
                best_cluster = ci
        if best_cluster >= 0:
            cluster_map[i] = best_cluster
        else:
            cluster_map[i] = len(cluster_reps)
            # Label from top 2 TF-IDF terms
            top_terms = sorted(vectors[i].items(), key=lambda x: x[1], reverse=True)[:2]
            label = "-".join(t[0] for t in top_terms) if top_terms else "misc"
            cluster_reps.append(i)
            cluster_labels.append(label)

    for i, a in enumerate(articles):
        a.cluster_id = cluster_labels[cluster_map[i]]

    # Count cluster sizes for logging
    cluster_sizes = Counter(cluster_map)
    multi = sum(1 for v in cluster_sizes.values() if v > 1)
    logger.info("Clustering: %d articles → %d clusters (%d with 2+ articles)",
                len(articles), len(cluster_reps), multi)

    return articles


# ── Source Diversity ─────────────────────────────────────────────────────────

def _enforce_source_diversity(articles: list['AnalysedArticle'], max_per_source: int = 3) -> list['AnalysedArticle']:
    """Cap articles per source to ensure variety in the digest."""
    source_counts: dict[str, int] = {}
    diverse: list[AnalysedArticle] = []
    for a in articles:
        key = a.source.lower().split(" - ")[0].split(" | ")[0][:30]
        count = source_counts.get(key, 0)
        if count < max_per_source:
            diverse.append(a)
            source_counts[key] = count + 1
    return diverse


# ── Public API ────────────────────────────────────────────────────────────────

async def analyse(articles: list[RawArticle]) -> list[AnalysedArticle]:
    if not articles:
        return []

    has_llm = config.GEMINI_API_KEY or config.OPENAI_API_KEY

    # Load source quality from recent history (auto-boost proven sources)
    try:
        import database
        _source_quality = database.get_source_quality_scores()
    except Exception:
        _source_quality = {}

    # Step 1: Heuristic score everything
    heuristic_results = [_heuristic_score(a) for a in articles]

    # Step 1.5: Apply dynamic source quality boost
    if _source_quality:
        for i, article in enumerate(articles):
            src = article.source
            if src in _source_quality:
                avg = _source_quality[src]
                if avg >= 65:
                    heuristic_results[i]["priority"] = min(100, heuristic_results[i].get("priority", 0) + 12)
                elif avg >= 50:
                    heuristic_results[i]["priority"] = min(100, heuristic_results[i].get("priority", 0) + 6)
                elif avg < 25:
                    heuristic_results[i]["priority"] = max(0, heuristic_results[i].get("priority", 0) - 10)
        logger.info("Dynamic source boost applied from %d tracked sources", len(_source_quality))

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

    # Source diversity — max 3 from same source
    analysed = _enforce_source_diversity(analysed, max_per_source=3)

    # Cluster related stories
    analysed = _cluster_articles(analysed)

    logger.info("Analysis: %d articles passed filters (min score %d)", len(analysed), config.MIN_PRIORITY_SCORE)
    return analysed
