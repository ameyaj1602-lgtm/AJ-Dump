"""
Alerting layer — Telegram, Email digest, CLI dashboard.
Features: daily email at 8:30 AM, Telegram alerts, dynamic dashboard.
"""

import asyncio
import logging
import shutil
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import unescape

import httpx

import config
import database
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


# ── Email Digest ──────────────────────────────────────────────────────────────

def _build_email_html(articles: list[dict]) -> str:
    """Build a beautiful HTML email from article dicts."""
    today = datetime.now().strftime("%A, %B %d, %Y")

    rows = ""
    for a in articles:
        title = unescape(a.get("title", ""))
        summary = unescape(a.get("summary", ""))
        source = a.get("source", "")
        url = a.get("url", "")
        priority = a.get("priority", 0)
        tags = a.get("tags", "")

        if priority >= 70:
            color = "#e74c3c"
            badge = "HIGH"
        elif priority >= 50:
            color = "#f39c12"
            badge = "MED"
        else:
            color = "#27ae60"
            badge = "LOW"

        tag_badges = ""
        for t in (tags.split(",") if tags else [])[:3]:
            t = t.strip()
            if t:
                tag_badges += f'<span style="background:#eee;color:#555;padding:2px 6px;border-radius:3px;font-size:11px;margin-right:4px;">#{t}</span>'

        rows += f"""
        <tr>
          <td style="padding:12px 16px;border-bottom:1px solid #eee;">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
              <span style="background:{color};color:white;padding:2px 8px;border-radius:3px;font-size:11px;font-weight:bold;">{badge} {priority}</span>
              <span style="color:#888;font-size:12px;">{source}</span>
            </div>
            <a href="{url}" style="color:#1a1a1a;text-decoration:none;font-size:15px;font-weight:600;line-height:1.3;">{title}</a>
            <div style="color:#666;font-size:13px;margin-top:4px;line-height:1.4;">{summary}</div>
            <div style="margin-top:6px;">{tag_badges}</div>
          </td>
        </tr>"""

    return f"""
    <html>
    <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;margin:0;padding:0;background:#f5f5f5;">
      <div style="max-width:640px;margin:0 auto;background:white;">
        <div style="background:linear-gradient(135deg,#1a1a2e,#16213e);padding:24px 20px;text-align:center;">
          <h1 style="color:white;margin:0;font-size:22px;">📡 News Intelligence Digest</h1>
          <p style="color:#aaa;margin:6px 0 0;font-size:13px;">{today} · {len(articles)} top stories</p>
        </div>
        <table style="width:100%;border-collapse:collapse;">
          {rows}
        </table>
        <div style="padding:16px;text-align:center;color:#999;font-size:11px;">
          Powered by News Intelligence Agent · Free & open source
        </div>
      </div>
    </body>
    </html>"""


def send_email_digest() -> bool:
    """Send a daily email digest of top articles from the last 24 hours."""
    if not config.EMAIL_ENABLED:
        return False
    if not config.EMAIL_FROM or not config.EMAIL_PASSWORD or not config.EMAIL_TO:
        logger.warning("Email not configured — set EMAIL_FROM, EMAIL_PASSWORD, EMAIL_TO in .env")
        return False

    # Get top articles from last 24 hours
    articles = database.get_recent(limit=30, min_priority=config.MIN_PRIORITY_SCORE)
    if not articles:
        logger.info("No articles for email digest")
        return False

    today = datetime.now().strftime("%b %d")
    subject = f"📡 News Digest — {today} — {len(articles)} top stories"

    # Build both plain text and HTML versions
    plain_lines = [f"NEWS INTELLIGENCE DIGEST — {today}", f"{len(articles)} top stories\n", "=" * 50, ""]
    for a in articles:
        emoji = "🔴" if a["priority"] >= 70 else "🟡" if a["priority"] >= 50 else "🟢"
        plain_lines.append(f"{emoji} [{a['priority']}] {unescape(a['title'])}")
        plain_lines.append(f"   {unescape(a.get('summary', ''))}")
        plain_lines.append(f"   📰 {a['source']}  🔗 {a.get('url', '')}")
        plain_lines.append("")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.EMAIL_FROM
    msg["To"] = config.EMAIL_TO

    msg.attach(MIMEText("\n".join(plain_lines), "plain"))
    msg.attach(MIMEText(_build_email_html(articles), "html"))

    try:
        with smtplib.SMTP(config.EMAIL_SMTP_HOST, config.EMAIL_SMTP_PORT) as server:
            server.starttls()
            server.login(config.EMAIL_FROM, config.EMAIL_PASSWORD)
            server.send_message(msg)
        logger.info("📧 Email digest sent to %s (%d articles)", config.EMAIL_TO, len(articles))
        return True
    except Exception as exc:
        logger.error("Email failed: %s", exc)
        return False


def should_send_digest() -> bool:
    """Check if current time matches the configured digest time (within 2-min window)."""
    if not config.EMAIL_ENABLED:
        return False
    now = datetime.now()
    return (now.hour == config.EMAIL_DIGEST_HOUR
            and config.EMAIL_DIGEST_MINUTE <= now.minute < config.EMAIL_DIGEST_MINUTE + 2)


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
