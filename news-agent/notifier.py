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

_JUNK_URLS = ["https://news.google.com", "https://www.bbc.com/news",
              "https://text.npr.org/", "https://www.aljazeera.com/"]


def _has_real_link(url: str) -> bool:
    """Check if the URL is a real article link, not a generic homepage."""
    if not url:
        return False
    for junk in _JUNK_URLS:
        if url.strip().rstrip("/") == junk.rstrip("/"):
            return False
    return url.startswith("http")


def _build_email_html(articles: list[dict]) -> str:
    """Build a premium HTML email digest."""
    today = datetime.now().strftime("%A, %B %d, %Y")
    count = len(articles)

    rows = ""
    rank = 0
    for a in articles:
        title = unescape(a.get("title", ""))
        summary = unescape(a.get("summary", ""))
        source = a.get("source", "")
        url = a.get("url", "")
        priority = a.get("priority", 0)
        tags = a.get("tags", "")
        has_link = _has_real_link(url)
        rank += 1

        if priority >= 70:
            color = "#e74c3c"
            bg = "#fef2f2"
            badge = "🔴 HIGH"
            border_color = "#e74c3c"
        elif priority >= 50:
            color = "#f59e0b"
            bg = "#fffbeb"
            badge = "🟡 MED"
            border_color = "#f59e0b"
        else:
            color = "#10b981"
            bg = "#f0fdf4"
            badge = "🟢 LOW"
            border_color = "#10b981"

        tag_badges = ""
        for t in (tags.split(",") if tags else [])[:4]:
            t = t.strip()
            if t and t != "general":
                tag_badges += f'<span style="background:#f1f5f9;color:#475569;padding:3px 8px;border-radius:12px;font-size:11px;margin-right:4px;display:inline-block;">{t}</span>'

        # Title — clickable if real link exists
        if has_link:
            title_html = f'<a href="{url}" style="color:#0f172a;text-decoration:none;font-size:16px;font-weight:700;line-height:1.4;display:block;">{title}</a>'
        else:
            title_html = f'<span style="color:#0f172a;font-size:16px;font-weight:700;line-height:1.4;display:block;">{title}</span>'

        # Summary — only show if different from title
        summary_html = ""
        if summary and summary.lower()[:40] != title.lower()[:40]:
            summary_html = f'<div style="color:#64748b;font-size:13px;margin-top:6px;line-height:1.5;">{summary[:180]}</div>'

        # Read button
        read_btn = ""
        if has_link:
            read_btn = f'<a href="{url}" style="display:inline-block;margin-top:8px;padding:6px 16px;background:{color};color:white;text-decoration:none;border-radius:6px;font-size:12px;font-weight:600;">Read →</a>'

        rows += f"""
        <tr>
          <td style="padding:0;">
            <div style="margin:8px 16px;padding:16px;background:{bg};border-left:4px solid {border_color};border-radius:8px;">
              <table style="width:100%;"><tr>
                <td style="vertical-align:top;">
                  <div style="margin-bottom:8px;">
                    <span style="background:{color};color:white;padding:3px 10px;border-radius:4px;font-size:11px;font-weight:700;letter-spacing:0.5px;">{priority}</span>
                    <span style="color:#94a3b8;font-size:12px;margin-left:8px;">{source}</span>
                  </div>
                  {title_html}
                  {summary_html}
                  <div style="margin-top:10px;">{tag_badges} {read_btn}</div>
                </td>
              </tr></table>
            </div>
          </td>
        </tr>"""

    return f"""
    <html>
    <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;margin:0;padding:0;background:#f1f5f9;">
      <div style="max-width:640px;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden;margin-top:20px;margin-bottom:20px;box-shadow:0 4px 6px rgba(0,0,0,0.07);">

        <!-- Header -->
        <div style="background:linear-gradient(135deg,#0f172a 0%,#1e293b 50%,#334155 100%);padding:32px 24px;text-align:center;">
          <div style="font-size:36px;margin-bottom:8px;">📡</div>
          <h1 style="color:#ffffff;margin:0;font-size:24px;font-weight:800;letter-spacing:-0.5px;">News Intelligence Digest</h1>
          <p style="color:#94a3b8;margin:8px 0 0;font-size:14px;">{today}</p>
          <div style="margin-top:12px;">
            <span style="background:rgba(255,255,255,0.15);color:#e2e8f0;padding:4px 14px;border-radius:20px;font-size:13px;font-weight:600;">{count} top stories</span>
          </div>
        </div>

        <!-- Quick Stats -->
        <div style="display:flex;text-align:center;padding:16px 8px;background:#f8fafc;border-bottom:1px solid #e2e8f0;">
          <table style="width:100%;"><tr>
            <td style="text-align:center;padding:8px;">
              <div style="font-size:20px;font-weight:800;color:#e74c3c;">{sum(1 for a in articles if a.get('priority',0) >= 70)}</div>
              <div style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;">High Priority</div>
            </td>
            <td style="text-align:center;padding:8px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;">
              <div style="font-size:20px;font-weight:800;color:#f59e0b;">{sum(1 for a in articles if 50 <= a.get('priority',0) < 70)}</div>
              <div style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;">Medium</div>
            </td>
            <td style="text-align:center;padding:8px;">
              <div style="font-size:20px;font-weight:800;color:#10b981;">{sum(1 for a in articles if a.get('priority',0) < 50)}</div>
              <div style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;">Notable</div>
            </td>
          </tr></table>
        </div>

        <!-- Articles -->
        <table style="width:100%;border-collapse:collapse;">
          {rows}
        </table>

        <!-- Footer -->
        <div style="padding:20px;text-align:center;background:#f8fafc;border-top:1px solid #e2e8f0;">
          <p style="color:#94a3b8;font-size:11px;margin:0;">Powered by <strong>News Intelligence Agent</strong> · Free & open source</p>
          <p style="color:#cbd5e1;font-size:10px;margin:4px 0 0;">Delivered automatically at 8:30 AM · Scoring 500+ sources every 2 min</p>
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

    # Get top articles — prefer ones with real links, cap at 15
    raw_articles = database.get_recent(limit=100, min_priority=config.MIN_PRIORITY_SCORE)
    # Prioritise articles with real links
    with_links = [a for a in raw_articles if _has_real_link(a.get("url", ""))]
    without_links = [a for a in raw_articles if not _has_real_link(a.get("url", ""))]
    articles = (with_links + without_links)[:15]
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
