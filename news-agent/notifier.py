"""
Alerting layer — Telegram notifications + CLI dashboard.
Features: dynamic terminal width, HTML cleanup, priority filtering, rate limiting.
"""

import asyncio
import logging
import shutil
from html import unescape

import httpx

import config
from analyzer import AnalysedArticle

logger = logging.getLogger(__name__)


# ── Telegram ──────────────────────────────────────────────────────────────────

async def send_telegram(article: AnalysedArticle) -> bool:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False

    priority_emoji = "🔴" if article.priority >= 70 else "🟡" if article.priority >= 50 else "🟢"
    tags_str = " ".join(f"#{t}" for t in article.tags[:4])

    text = (
        f"{priority_emoji} <b>{_escape_html(article.title)}</b>\n"
        f"🧠 {_escape_html(article.summary)}\n"
        f"📰 {_escape_html(article.source)} · Score: {article.priority}/100\n"
        f"🏷 {tags_str}\n"
        f'🔗 <a href="{article.url}">Read more</a>'
    )

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text,
                      "parse_mode": "HTML", "disable_web_page_preview": True},
                timeout=10,
            )
            if resp.status_code == 200:
                return True
            if resp.status_code == 429:
                retry_after = resp.json().get("parameters", {}).get("retry_after", 5)
                logger.warning("Telegram rate limited, waiting %ds", retry_after)
                await asyncio.sleep(retry_after)
                return False
            logger.warning("Telegram %d: %s", resp.status_code, resp.text[:100])
            return False
    except Exception as exc:
        logger.warning("Telegram failed: %s", str(exc)[:60])
        return False


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── CLI Dashboard ─────────────────────────────────────────────────────────────

def print_dashboard(articles: list[AnalysedArticle]) -> None:
    # Filter and cap
    articles = [a for a in articles if a.priority >= config.MIN_PRIORITY_SCORE]
    articles = articles[:config.DASHBOARD_MAX_ARTICLES]

    if not articles:
        print("  No high-priority alerts this cycle.\n")
        return

    try:
        width = max(shutil.get_terminal_size().columns, 80)
    except Exception:
        width = 100
    width = min(width, 120)
    inner = width - 2

    print("┌" + "─" * inner + "┐")
    header = "📡 NEWS INTELLIGENCE DASHBOARD"
    print(f"│{header:^{inner}}│")
    print("├" + "─" * inner + "┤")

    for a in articles:
        emoji = "🔴" if a.priority >= 70 else "🟡" if a.priority >= 50 else "🟢"
        tags = " ".join(f"#{t}" for t in a.tags[:3])

        # Clean up any remaining HTML entities
        title = unescape(a.title)
        summary = unescape(a.summary)

        title_line = f"  {emoji} [{a.priority:3d}] {title[:inner - 14]}"
        print(f"│{title_line:<{inner}}│")

        summary_line = f"       🧠 {summary[:inner - 12]}"
        print(f"│{summary_line:<{inner}}│")

        meta_line = f"       📰 {a.source[:25]} {tags}"
        print(f"│{meta_line:<{inner}}│")

        print("│" + " " * inner + "│")

    print("└" + "─" * inner + "┘")
    print(f"  Showing top {len(articles)} articles (score >= {config.MIN_PRIORITY_SCORE})\n")


# ── Public API ────────────────────────────────────────────────────────────────

async def send_alerts(articles: list[AnalysedArticle]) -> int:
    sent = 0
    for article in articles:
        if article.priority < config.MIN_PRIORITY_SCORE:
            continue
        ok = await send_telegram(article)
        if ok:
            sent += 1
        await asyncio.sleep(0.5)
    if sent:
        logger.info("Sent %d Telegram alerts", sent)
    return sent
