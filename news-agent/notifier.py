"""
Alerting layer — sends notifications via Telegram (primary) and optional email.
Also provides a CLI dashboard view.
"""

import asyncio
import logging
import smtplib
from email.mime.text import MIMEText
from typing import Optional

import httpx

import config
from analyzer import AnalysedArticle

logger = logging.getLogger(__name__)


# ── Telegram ──────────────────────────────────────────────────────────────────

async def send_telegram(article: AnalysedArticle) -> bool:
    """Send a single alert to Telegram."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False

    priority_emoji = "🔴" if article.priority >= 70 else "🟡" if article.priority >= 50 else "🟢"
    tags_str = " ".join(f"#{t}" for t in article.tags)

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
                json={
                    "chat_id": config.TELEGRAM_CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                return True
            logger.warning("Telegram API error %d: %s", resp.status_code, resp.text)
            return False
    except Exception as exc:
        logger.warning("Telegram send failed: %s", exc)
        return False


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── Email (optional) ─────────────────────────────────────────────────────────

def send_email(
    article: AnalysedArticle,
    smtp_host: str = "",
    smtp_port: int = 587,
    smtp_user: str = "",
    smtp_pass: str = "",
    to_addr: str = "",
) -> bool:
    """Send an email alert (configure via env vars or pass directly)."""
    smtp_host = smtp_host or config.__dict__.get("SMTP_HOST", "")
    if not smtp_host or not to_addr:
        return False

    subject = f"[News Alert] {article.title[:80]}"
    body = (
        f"Headline: {article.title}\n"
        f"Summary: {article.summary}\n"
        f"Source: {article.source}\n"
        f"Priority: {article.priority}/100\n"
        f"Tags: {', '.join(article.tags)}\n"
        f"Link: {article.url}\n"
    )

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_addr

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return True
    except Exception as exc:
        logger.warning("Email send failed: %s", exc)
        return False


# ── CLI Dashboard ─────────────────────────────────────────────────────────────

def print_dashboard(articles: list[AnalysedArticle]) -> None:
    """Print a clean CLI dashboard of latest alerts."""
    if not articles:
        print("  No new alerts this cycle.\n")
        return

    width = 80
    print("┌" + "─" * (width - 2) + "┐")
    print(f"│{'  📡 NEWS INTELLIGENCE DASHBOARD':^{width - 2}}│")
    print("├" + "─" * (width - 2) + "┤")

    for a in articles:
        emoji = "🔴" if a.priority >= 70 else "🟡" if a.priority >= 50 else "🟢"
        tags = " ".join(f"#{t}" for t in a.tags[:3])

        title_line = f"  {emoji} [{a.priority:3d}] {a.title[:60]}"
        print(f"│{title_line:<{width - 2}}│")

        summary_line = f"       🧠 {a.summary[:60]}"
        print(f"│{summary_line:<{width - 2}}│")

        meta_line = f"       📰 {a.source[:25]} {tags}"
        print(f"│{meta_line:<{width - 2}}│")

        print("│" + " " * (width - 2) + "│")

    print("└" + "─" * (width - 2) + "┘")


# ── Public API ────────────────────────────────────────────────────────────────

async def send_alerts(articles: list[AnalysedArticle]) -> int:
    """Send alerts for all articles. Returns count of successfully sent."""
    sent = 0
    for article in articles:
        ok = await send_telegram(article)
        if ok:
            sent += 1
        # Rate-limit to avoid Telegram throttling
        await asyncio.sleep(0.3)

    if sent:
        logger.info("Sent %d/%d Telegram alerts", sent, len(articles))
    return sent
