"""
Configuration module — loads settings from .env and provides defaults.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).parent / ".env")


# ── LLM API Keys ─────────────────────────────────────────────────────────────
# Google Gemini (FREE — default). Get key at https://aistudio.google.com/apikey
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# OpenAI-compatible fallback (optional, only used if GEMINI_API_KEY is empty)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Polling ───────────────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "120"))

# ── RSS Feeds ─────────────────────────────────────────────────────────────────
RSS_FEEDS = [
    # Google News – Top Stories
    "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
    # Google News – India
    "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",
    # TechCrunch
    "https://techcrunch.com/feed/",
    # Reuters – World
    "https://www.reutersagency.com/feed/?best-topics=tech",
    # Economic Times – India
    "https://economictimes.indiatimes.com/rssfeedstopstories.cms",
    # Hacker News (front page)
    "https://hnrss.org/frontpage",
    # Ars Technica
    "https://feeds.arstechnica.com/arstechnica/index",
]

# ── Filters ───────────────────────────────────────────────────────────────────
# Keywords to boost priority (case-insensitive). Articles matching these get +20 score.
PRIORITY_KEYWORDS = [
    kw.strip()
    for kw in os.getenv(
        "PRIORITY_KEYWORDS",
        "AI,funding,layoffs,startup,IPO,acquisition,regulation,open source,GPT,LLM",
    ).split(",")
    if kw.strip()
]

# If non-empty, ONLY articles matching at least one keyword are forwarded.
FILTER_KEYWORDS = [
    kw.strip()
    for kw in os.getenv("FILTER_KEYWORDS", "").split(",")
    if kw.strip()
]

# Minimum priority score (0–100) to trigger an alert.
MIN_PRIORITY_SCORE = int(os.getenv("MIN_PRIORITY_SCORE", "30"))

# ── Database ──────────────────────────────────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", str(Path(__file__).parent / "news.db"))

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
