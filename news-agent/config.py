"""
Configuration module — loads settings from .env and provides defaults.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).parent / ".env")


# ── LLM API Keys ─────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Email Digest ──────────────────────────────────────────────────────────────
EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "false").lower() in ("true", "1", "yes")
EMAIL_SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))
EMAIL_FROM = os.getenv("EMAIL_FROM", "")         # your Gmail address
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")  # Gmail App Password
EMAIL_TO = os.getenv("EMAIL_TO", "")              # recipient (can be same as FROM)
EMAIL_DIGEST_HOUR = int(os.getenv("EMAIL_DIGEST_HOUR", "8"))    # 24h format
EMAIL_DIGEST_MINUTE = int(os.getenv("EMAIL_DIGEST_MINUTE", "30"))

# ── Polling ───────────────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "120"))

# ── RSS Feeds (expanded — 20+ sources) ────────────────────────────────────────
RSS_FEEDS = [
    # Global top news
    "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",
    "https://feeds.bbci.co.uk/news/rss.xml",
    "https://rss.cnn.com/rss/edition.rss",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://www.theguardian.com/world/rss",
    # Tech
    "https://techcrunch.com/feed/",
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://www.theverge.com/rss/index.xml",
    "https://www.wired.com/feed/rss",
    # Finance / Business
    "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    # India — News
    "https://economictimes.indiatimes.com/rssfeedstopstories.cms",
    "https://economictimes.indiatimes.com/rssfeedstopstories.cms",
    "https://indianexpress.com/feed/",
    "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
    "https://www.thehindu.com/news/feeder/default.rss",
    "https://www.livemint.com/rss/news",
    "https://www.livemint.com/rss/companies",
    "https://www.livemint.com/rss/technology",
    "https://www.business-standard.com/rss/home_page_top_stories.rss",
    "https://www.moneycontrol.com/rss/latestnews.xml",
    "https://www.ndtv.com/rss/top-stories",
    # Hacker News
    "https://hnrss.org/frontpage",
]

# ── Filters ───────────────────────────────────────────────────────────────────
PRIORITY_KEYWORDS = [
    kw.strip()
    for kw in os.getenv(
        "PRIORITY_KEYWORDS",
        "AI,funding,layoffs,startup,IPO,acquisition,regulation,open source,"
        "GPT,LLM,breakthrough,sanctions,election,crash,surge,hack,breach,"
        "launch,partnership,recall",
    ).split(",")
    if kw.strip()
]

FILTER_KEYWORDS = [
    kw.strip()
    for kw in os.getenv("FILTER_KEYWORDS", "").split(",")
    if kw.strip()
]

MIN_PRIORITY_SCORE = int(os.getenv("MIN_PRIORITY_SCORE", "40"))

# ── Dashboard ─────────────────────────────────────────────────────────────────
DASHBOARD_MAX_ARTICLES = int(os.getenv("DASHBOARD_MAX_ARTICLES", "30"))

# ── Database ──────────────────────────────────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", str(Path(__file__).parent / "news.db"))
MAX_ARTICLE_AGE_HOURS = int(os.getenv("MAX_ARTICLE_AGE_HOURS", "48"))

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
