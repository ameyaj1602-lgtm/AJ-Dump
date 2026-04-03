"""
Alerting layer — Telegram, Email digest, CLI dashboard.
v2: Completely redesigned email with dark mode header, category sections,
    numbered rankings, mobile-friendly layout, and polished card design.
"""

import asyncio
import logging
import shutil
import smtplib
from collections import defaultdict
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import unescape
from urllib.parse import quote

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


# ── Email Digest (v2 — Premium Redesign) ────────────────────────────────────

_JUNK_URLS = ["https://news.google.com", "https://www.bbc.com/news",
              "https://text.npr.org/", "https://www.aljazeera.com/"]


def _has_real_link(url: str) -> bool:
    if not url:
        return False
    for junk in _JUNK_URLS:
        if url.strip().rstrip("/") == junk.rstrip("/"):
            return False
    return url.startswith("http")


# Tag display config
_TAG_COLORS = {
    "ai": ("#7c3aed", "#f5f3ff"),
    "finance": ("#059669", "#ecfdf5"),
    "startups": ("#d97706", "#fffbeb"),
    "geopolitics": ("#dc2626", "#fef2f2"),
    "tech": ("#2563eb", "#eff6ff"),
    "security": ("#be123c", "#fff1f2"),
    "science": ("#0891b2", "#ecfeff"),
    "india": ("#ea580c", "#fff7ed"),
    "crypto": ("#7c3aed", "#faf5ff"),
    "health": ("#16a34a", "#f0fdf4"),
    "climate": ("#15803d", "#f0fdf4"),
    "legal": ("#4338ca", "#eef2ff"),
}

_TAG_EMOJI = {
    "ai": "🤖", "finance": "💰", "startups": "🚀", "geopolitics": "🌍",
    "tech": "💻", "security": "🔒", "science": "🔬", "india": "🇮🇳",
    "crypto": "₿", "health": "🏥", "climate": "🌱", "legal": "⚖️",
    "general": "📰",
}


def _build_article_card(a: dict, rank: int) -> str:
    title = unescape(a.get("title", ""))
    summary = unescape(a.get("summary", ""))
    source = a.get("source", "")
    url = a.get("url", "")
    priority = a.get("priority", 0)
    tags = a.get("tags", "")
    has_link = _has_real_link(url)

    # Priority styling
    if priority >= 70:
        accent = "#ef4444"
        bg = "#fef2f2"
        label = "HIGH"
    elif priority >= 50:
        accent = "#f59e0b"
        bg = "#fffbeb"
        label = "MEDIUM"
    else:
        accent = "#22c55e"
        bg = "#f0fdf4"
        label = "NOTABLE"

    # Tag pills
    tag_pills = ""
    for t in (tags.split(",") if tags else [])[:3]:
        t = t.strip()
        if t and t != "general":
            fg, pill_bg = _TAG_COLORS.get(t, ("#64748b", "#f1f5f9"))
            emoji = _TAG_EMOJI.get(t, "")
            tag_pills += f'<span style="background:{pill_bg};color:{fg};padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600;margin-right:4px;display:inline-block;border:1px solid {fg}22;">{emoji} {t}</span>'

    # Title
    if has_link:
        title_html = f'<a href="{url}" style="color:#1e293b;text-decoration:none;font-size:15px;font-weight:700;line-height:1.4;">{title}</a>'
    else:
        title_html = f'<span style="color:#1e293b;font-size:15px;font-weight:700;line-height:1.4;">{title}</span>'

    # Summary
    summary_html = ""
    if summary and summary.lower()[:40] != title.lower()[:40]:
        summary_html = f'<div style="color:#64748b;font-size:13px;margin-top:6px;line-height:1.5;">{summary[:160]}</div>'

    # Action buttons
    google_url = f"https://www.google.com/search?q={quote(title[:80])}&tbm=nws"
    x_url = f"https://x.com/search?q={quote(title[:60])}&f=live"

    btn_base = "display:inline-block;margin-top:10px;margin-right:6px;padding:7px 16px;text-decoration:none;border-radius:8px;font-size:11px;font-weight:700;letter-spacing:0.3px;"

    buttons = ""
    if has_link:
        buttons += f'<a href="{url}" style="{btn_base}background:{accent};color:white;">Read Article →</a>'
    buttons += f'<a href="{google_url}" style="{btn_base}background:#1a73e8;color:white;">🔍 Google</a>'
    buttons += f'<a href="{x_url}" style="{btn_base}background:#000000;color:white;">𝕏 Search</a>'

    return f"""
    <tr><td style="padding:6px 16px;">
      <div style="background:{bg};border-left:4px solid {accent};border-radius:12px;padding:18px 20px;box-shadow:0 1px 3px rgba(0,0,0,0.04);">
        <table style="width:100%;border-collapse:collapse;"><tr><td>
          <!-- Rank + Score + Source -->
          <div style="margin-bottom:10px;display:flex;align-items:center;">
            <span style="background:{accent};color:white;padding:2px 10px;border-radius:6px;font-size:12px;font-weight:800;letter-spacing:0.5px;">#{rank}</span>
            <span style="background:{accent}18;color:{accent};padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;margin-left:6px;">{priority}/100 {label}</span>
            <span style="color:#94a3b8;font-size:12px;margin-left:8px;">via {source[:30]}</span>
          </div>
          <!-- Title -->
          <div>{title_html}</div>
          {summary_html}
          <!-- Tags -->
          <div style="margin-top:10px;">{tag_pills}</div>
          <!-- Buttons -->
          <div>{buttons}</div>
        </td></tr></table>
      </div>
    </td></tr>"""


def _build_email_html(articles: list[dict]) -> str:
    today = datetime.now().strftime("%A, %B %d, %Y")
    now_time = datetime.now().strftime("%I:%M %p")
    count = len(articles)

    high = sum(1 for a in articles if a.get('priority', 0) >= 70)
    med = sum(1 for a in articles if 50 <= a.get('priority', 0) < 70)
    low = sum(1 for a in articles if a.get('priority', 0) < 50)

    # Collect unique tags for summary
    all_tags = set()
    for a in articles:
        for t in (a.get("tags", "").split(",") if a.get("tags") else []):
            t = t.strip()
            if t and t != "general":
                all_tags.add(t)

    tag_summary = " ".join(f'{_TAG_EMOJI.get(t, "📌")} {t.title()}' for t in sorted(all_tags)[:8])

    # Build article cards
    cards_html = ""
    for i, a in enumerate(articles):
        cards_html += _build_article_card(a, i + 1)

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;margin:0;padding:0;background:#f0f2f5;-webkit-font-smoothing:antialiased;">

  <!-- Wrapper -->
  <div style="max-width:620px;margin:0 auto;padding:16px;">

    <!-- Header Card -->
    <div style="background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%);border-radius:16px;padding:32px 28px;text-align:center;margin-bottom:12px;">
      <div style="font-size:42px;margin-bottom:4px;">📡</div>
      <h1 style="color:#ffffff;margin:0;font-size:22px;font-weight:800;letter-spacing:-0.5px;">News Intelligence</h1>
      <p style="color:#94a3b8;margin:6px 0 0;font-size:13px;">{today} · {now_time}</p>

      <!-- Stats Row -->
      <div style="margin-top:20px;background:rgba(255,255,255,0.08);border-radius:12px;padding:14px;">
        <table style="width:100%;border-collapse:collapse;"><tr>
          <td style="text-align:center;width:25%;">
            <div style="font-size:24px;font-weight:800;color:#ffffff;">{count}</div>
            <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1px;margin-top:2px;">Stories</div>
          </td>
          <td style="text-align:center;width:25%;border-left:1px solid rgba(255,255,255,0.1);">
            <div style="font-size:24px;font-weight:800;color:#ef4444;">{high}</div>
            <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1px;margin-top:2px;">Critical</div>
          </td>
          <td style="text-align:center;width:25%;border-left:1px solid rgba(255,255,255,0.1);">
            <div style="font-size:24px;font-weight:800;color:#f59e0b;">{med}</div>
            <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1px;margin-top:2px;">Important</div>
          </td>
          <td style="text-align:center;width:25%;border-left:1px solid rgba(255,255,255,0.1);">
            <div style="font-size:24px;font-weight:800;color:#22c55e;">{low}</div>
            <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1px;margin-top:2px;">Notable</div>
          </td>
        </tr></table>
      </div>
    </div>

    <!-- Topics Bar -->
    <div style="background:#ffffff;border-radius:12px;padding:14px 20px;margin-bottom:12px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
      <div style="font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:6px;font-weight:700;">Today's Topics</div>
      <div style="font-size:13px;color:#475569;line-height:1.8;">{tag_summary}</div>
    </div>

    <!-- Articles -->
    <div style="background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
      <div style="padding:16px 20px 8px;border-bottom:1px solid #f1f5f9;">
        <span style="font-size:14px;font-weight:700;color:#1e293b;">Top Stories</span>
        <span style="font-size:12px;color:#94a3b8;margin-left:8px;">ranked by intelligence score</span>
      </div>
      <table style="width:100%;border-collapse:collapse;">
        {cards_html}
      </table>
    </div>

    <!-- Footer -->
    <div style="text-align:center;padding:20px 16px;margin-top:8px;">
      <p style="color:#94a3b8;font-size:11px;margin:0;">
        Powered by <strong style="color:#64748b;">News Intelligence Agent</strong>
      </p>
      <p style="color:#cbd5e1;font-size:10px;margin:4px 0 0;">
        Scanning 600+ sources · Scoring & ranking with AI · Delivered daily
      </p>
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
    with_links = [a for a in raw_articles if _has_real_link(a.get("url", ""))]
    without_links = [a for a in raw_articles if not _has_real_link(a.get("url", ""))]
    articles = (with_links + without_links)[:15]
    if not articles:
        logger.info("No articles for email digest")
        return False

    today = datetime.now().strftime("%b %d")
    high = sum(1 for a in articles if a.get("priority", 0) >= 70)
    subject = f"📡 {today} — {len(articles)} stories"
    if high:
        subject += f" ({high} critical)"

    # Build both plain text and HTML versions
    plain_lines = [f"NEWS INTELLIGENCE DIGEST — {today}", f"{len(articles)} top stories\n", "=" * 50, ""]
    for i, a in enumerate(articles):
        emoji = "🔴" if a["priority"] >= 70 else "🟡" if a["priority"] >= 50 else "🟢"
        plain_lines.append(f"#{i+1} {emoji} [{a['priority']}] {unescape(a['title'])}")
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
