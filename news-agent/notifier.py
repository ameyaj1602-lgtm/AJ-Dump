"""
Alerting layer — Telegram, Email digest, CLI dashboard.
v3: Three-section email — General News, Business & Finance, AI & Tech.
    Landing page hero, column layout per section, clean minimal cards.
"""

import asyncio
import logging
import shutil
import smtplib
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


# ── Email Digest (v3 — Three-Section Layout) ────────────────────────────────

_JUNK_URLS = ["https://news.google.com", "https://www.bbc.com/news",
              "https://text.npr.org/", "https://www.aljazeera.com/"]


def _has_real_link(url: str) -> bool:
    if not url:
        return False
    for junk in _JUNK_URLS:
        if url.strip().rstrip("/") == junk.rstrip("/"):
            return False
    return url.startswith("http")


# ── Section Config ───────────────────────────────────────────────────────────

_SECTIONS = [
    {
        "id": "general",
        "title": "Top Stories",
        "subtitle": "Breaking news from around the world",
        "icon": "🌍",
        "accent": "#0f172a",
        "gradient": "linear-gradient(135deg,#0f172a 0%,#334155 100%)",
        "tags": {"geopolitics", "health", "climate", "legal", "science", "security", "general"},
        "max": 7,
    },
    {
        "id": "business",
        "title": "Business & Finance",
        "subtitle": "Markets, startups, and economy",
        "icon": "💰",
        "accent": "#059669",
        "gradient": "linear-gradient(135deg,#064e3b 0%,#059669 100%)",
        "tags": {"finance", "startups", "crypto", "india"},
        "max": 7,
    },
    {
        "id": "ai",
        "title": "AI & Technology",
        "subtitle": "Artificial intelligence, tech giants, and innovation",
        "icon": "🤖",
        "accent": "#7c3aed",
        "gradient": "linear-gradient(135deg,#4c1d95 0%,#7c3aed 100%)",
        "tags": {"ai", "tech"},
        "max": 7,
    },
]


def _categorize_articles(articles: list[dict]) -> dict[str, list[dict]]:
    """Sort articles into the 3 sections. An article goes to the first matching section."""
    buckets: dict[str, list[dict]] = {s["id"]: [] for s in _SECTIONS}
    used = set()

    for section in _SECTIONS:
        for a in articles:
            if id(a) in used:
                continue
            tags = set(t.strip() for t in (a.get("tags", "") or "").split(",") if t.strip())
            if tags & section["tags"]:
                if len(buckets[section["id"]]) < section["max"]:
                    buckets[section["id"]].append(a)
                    used.add(id(a))

    # Remaining uncategorized → general
    for a in articles:
        if id(a) not in used and len(buckets["general"]) < _SECTIONS[0]["max"]:
            buckets["general"].append(a)
            used.add(id(a))

    return buckets


def _build_article_row(a: dict, rank: int, accent: str) -> str:
    """Build a single article card for email."""
    title = unescape(a.get("title", ""))
    summary = unescape(a.get("summary", ""))
    source = a.get("source", "")
    url = a.get("url", "")
    priority = a.get("priority", 0)
    has_link = _has_real_link(url)

    # Priority dot
    if priority >= 70:
        dot = "#ef4444"
    elif priority >= 50:
        dot = "#f59e0b"
    else:
        dot = "#22c55e"

    # Title
    if has_link:
        title_html = f'<a href="{url}" style="color:#1e293b;text-decoration:none;font-weight:700;font-size:14px;line-height:1.4;">{title[:100]}</a>'
    else:
        title_html = f'<span style="color:#1e293b;font-weight:700;font-size:14px;line-height:1.4;">{title[:100]}</span>'

    # Summary
    summary_html = ""
    if summary and summary.lower()[:40] != title.lower()[:40]:
        summary_html = f'<div style="color:#64748b;font-size:12px;margin-top:4px;line-height:1.5;">{summary[:140]}</div>'

    # Buttons
    google_url = f"https://www.google.com/search?q={quote(title[:80])}&tbm=nws"
    x_url = f"https://x.com/search?q={quote(title[:60])}&f=live"
    btn = "display:inline-block;margin-top:8px;margin-right:4px;padding:5px 12px;text-decoration:none;border-radius:6px;font-size:10px;font-weight:700;"

    buttons = ""
    if has_link:
        buttons += f'<a href="{url}" style="{btn}background:{accent};color:white;">Read →</a>'
    buttons += f'<a href="{google_url}" style="{btn}background:#1a73e8;color:white;">Google</a>'
    buttons += f'<a href="{x_url}" style="{btn}background:#000;color:white;">𝕏</a>'

    return f"""
    <tr><td style="padding:8px 0;border-bottom:1px solid #f1f5f9;">
      <table style="width:100%;border-collapse:collapse;"><tr>
        <td style="width:36px;vertical-align:top;padding-top:2px;">
          <div style="width:28px;height:28px;border-radius:8px;background:{accent}12;text-align:center;line-height:28px;font-size:12px;font-weight:800;color:{accent};">{rank}</div>
        </td>
        <td style="vertical-align:top;padding-left:8px;">
          <div style="display:flex;align-items:center;margin-bottom:2px;">
            <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{dot};margin-right:6px;"></span>
            <span style="color:#94a3b8;font-size:11px;">{source[:30]} · {priority}/100</span>
          </div>
          {title_html}
          {summary_html}
          <div>{buttons}</div>
        </td>
      </tr></table>
    </td></tr>"""


def _build_section(section: dict, articles: list[dict]) -> str:
    """Build one complete section block."""
    if not articles:
        return ""

    rows = ""
    for i, a in enumerate(articles):
        rows += _build_article_row(a, i + 1, section["accent"])

    return f"""
    <!-- {section['title']} Section -->
    <div style="background:#ffffff;border-radius:16px;margin:12px 0;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,0.06);">
      <!-- Section Header -->
      <div style="{section['gradient']};padding:20px 24px;">
        <table style="width:100%;border-collapse:collapse;"><tr>
          <td>
            <span style="font-size:24px;margin-right:8px;">{section['icon']}</span>
            <span style="color:#ffffff;font-size:18px;font-weight:800;letter-spacing:-0.3px;">{section['title']}</span>
            <div style="color:rgba(255,255,255,0.6);font-size:12px;margin-top:4px;">{section['subtitle']}</div>
          </td>
          <td style="text-align:right;vertical-align:top;">
            <span style="background:rgba(255,255,255,0.15);color:#e2e8f0;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600;">{len(articles)} stories</span>
          </td>
        </tr></table>
      </div>
      <!-- Articles -->
      <div style="padding:12px 20px;">
        <table style="width:100%;border-collapse:collapse;">
          {rows}
        </table>
      </div>
    </div>"""


def _build_email_html(articles: list[dict]) -> str:
    """Build the complete 3-section email."""
    today = datetime.now().strftime("%A, %B %d, %Y")
    now_time = datetime.now().strftime("%I:%M %p")
    count = len(articles)

    # Categorize
    buckets = _categorize_articles(articles)

    # Stats
    high = sum(1 for a in articles if a.get('priority', 0) >= 70)
    med = sum(1 for a in articles if 50 <= a.get('priority', 0) < 70)
    sources = len(set(a.get("source", "") for a in articles))

    # Build sections
    sections_html = ""
    for section in _SECTIONS:
        sections_html += _build_section(section, buckets[section["id"]])

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;margin:0;padding:0;background:#f0f2f5;-webkit-font-smoothing:antialiased;">

  <div style="max-width:640px;margin:0 auto;padding:16px;">

    <!-- ═══ HERO / LANDING PAGE ═══ -->
    <div style="background:linear-gradient(160deg,#0f172a 0%,#1e293b 40%,#0f172a 100%);border-radius:20px;padding:40px 28px 32px;text-align:center;margin-bottom:8px;position:relative;overflow:hidden;">

      <!-- Decorative circles -->
      <div style="position:absolute;top:-20px;right:-20px;width:120px;height:120px;border-radius:50%;background:rgba(124,58,237,0.1);"></div>
      <div style="position:absolute;bottom:-30px;left:-10px;width:80px;height:80px;border-radius:50%;background:rgba(5,150,105,0.1);"></div>

      <div style="font-size:48px;margin-bottom:8px;">📡</div>
      <h1 style="color:#ffffff;margin:0;font-size:26px;font-weight:900;letter-spacing:-0.5px;">News Intelligence</h1>
      <p style="color:#64748b;margin:8px 0 0;font-size:13px;font-weight:500;">{today}</p>

      <!-- Stats Grid -->
      <div style="margin-top:24px;display:inline-block;">
        <table style="border-collapse:collapse;margin:0 auto;"><tr>
          <td style="padding:0 12px;text-align:center;">
            <div style="font-size:28px;font-weight:900;color:#ffffff;">{count}</div>
            <div style="font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:1.5px;margin-top:2px;">Stories</div>
          </td>
          <td style="padding:0 12px;text-align:center;border-left:1px solid rgba(255,255,255,0.08);">
            <div style="font-size:28px;font-weight:900;color:#ef4444;">{high}</div>
            <div style="font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:1.5px;margin-top:2px;">Critical</div>
          </td>
          <td style="padding:0 12px;text-align:center;border-left:1px solid rgba(255,255,255,0.08);">
            <div style="font-size:28px;font-weight:900;color:#f59e0b;">{med}</div>
            <div style="font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:1.5px;margin-top:2px;">Important</div>
          </td>
          <td style="padding:0 12px;text-align:center;border-left:1px solid rgba(255,255,255,0.08);">
            <div style="font-size:28px;font-weight:900;color:#22c55e;">{sources}</div>
            <div style="font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:1.5px;margin-top:2px;">Sources</div>
          </td>
        </tr></table>
      </div>

      <!-- Section Quick Nav -->
      <div style="margin-top:20px;">
        <span style="display:inline-block;background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.1);color:#e2e8f0;padding:6px 16px;border-radius:20px;font-size:11px;font-weight:600;margin:3px;">🌍 Top Stories</span>
        <span style="display:inline-block;background:rgba(5,150,105,0.15);border:1px solid rgba(5,150,105,0.2);color:#6ee7b7;padding:6px 16px;border-radius:20px;font-size:11px;font-weight:600;margin:3px;">💰 Business</span>
        <span style="display:inline-block;background:rgba(124,58,237,0.15);border:1px solid rgba(124,58,237,0.2);color:#c4b5fd;padding:6px 16px;border-radius:20px;font-size:11px;font-weight:600;margin:3px;">🤖 AI & Tech</span>
      </div>
    </div>

    <!-- ═══ THREE SECTIONS ═══ -->
    {sections_html}

    <!-- ═══ FOOTER ═══ -->
    <div style="text-align:center;padding:20px 16px 8px;">
      <p style="color:#94a3b8;font-size:11px;margin:0;">
        Powered by <strong style="color:#64748b;">News Intelligence Agent</strong>
      </p>
      <p style="color:#cbd5e1;font-size:10px;margin:4px 0 0;">
        Scanning 600+ sources daily · AI-powered ranking · Delivered at {now_time}
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

    # Get top articles — prefer ones with real links
    raw_articles = database.get_recent(limit=150, min_priority=config.MIN_PRIORITY_SCORE)
    with_links = [a for a in raw_articles if _has_real_link(a.get("url", ""))]
    without_links = [a for a in raw_articles if not _has_real_link(a.get("url", ""))]
    articles = (with_links + without_links)[:21]  # 7 per section max
    if not articles:
        logger.info("No articles for email digest")
        return False

    today = datetime.now().strftime("%b %d")
    high = sum(1 for a in articles if a.get("priority", 0) >= 70)
    subject = f"📡 {today} — {len(articles)} stories"
    if high:
        subject += f" ({high} critical)"

    # Plain text fallback
    plain_lines = [f"NEWS INTELLIGENCE DIGEST — {today}", f"{len(articles)} top stories\n", "=" * 50, ""]
    for i, a in enumerate(articles):
        emoji = "🔴" if a["priority"] >= 70 else "🟡" if a["priority"] >= 50 else "🟢"
        plain_lines.append(f"#{i+1} {emoji} [{a['priority']}] {unescape(a['title'])}")
        plain_lines.append(f"   {unescape(a.get('summary', ''))}")
        plain_lines.append(f"   📰 {a['source']}  🔗 {a.get('url', '')}")
        plain_lines.append("")

    # Support multiple recipients (comma-separated in .env)
    recipients = [r.strip() for r in config.EMAIL_TO.split(",") if r.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.EMAIL_FROM
    msg["To"] = ", ".join(recipients)

    msg.attach(MIMEText("\n".join(plain_lines), "plain"))
    msg.attach(MIMEText(_build_email_html(articles), "html"))

    try:
        with smtplib.SMTP(config.EMAIL_SMTP_HOST, config.EMAIL_SMTP_PORT) as server:
            server.starttls()
            server.login(config.EMAIL_FROM, config.EMAIL_PASSWORD)
            server.sendmail(config.EMAIL_FROM, recipients, msg.as_string())
        logger.info("📧 Email digest sent to %s (%d articles)", ", ".join(recipients), len(articles))
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
