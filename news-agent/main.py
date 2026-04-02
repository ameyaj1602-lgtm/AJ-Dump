#!/usr/bin/env python3
"""
Real-Time News Intelligence Agent
──────────────────────────────────
Fetches → Deduplicates → Analyses → Ranks → Alerts

Usage:
    python main.py              # Run the agent loop
    python main.py --once       # Run one cycle and exit
    python main.py --dashboard  # Show recent alerts from DB
"""

import argparse
import asyncio
import logging
import signal
import sys
import time

import config
import database
import fetcher
import analyzer
import notifier

# ── Logging Setup ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s │ %(levelname)-7s │ %(name)-12s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("agent")

# Quiet down noisy libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


# ── Agent Loop ────────────────────────────────────────────────────────────────

_running = True


def _handle_signal(sig, frame):
    global _running
    logger.info("Shutdown signal received — finishing current cycle…")
    _running = False


async def run_cycle() -> int:
    """Run one fetch → analyse → alert cycle. Returns number of alerts sent."""
    logger.info("═══ Starting news cycle ═══")
    start = time.monotonic()

    # 1. Fetch
    raw_articles = await fetcher.fetch_all()
    if not raw_articles:
        logger.info("No new articles found.")
        return 0

    # 2. Analyse & filter
    analysed = await analyzer.analyse(raw_articles)

    # 3. Store in DB
    for a in analysed:
        database.insert_article(
            article_hash=a.hash,
            title=a.title,
            url=a.url,
            source=a.source,
            summary=a.summary,
            tags=",".join(a.tags),
            priority=a.priority,
            cluster_id=a.cluster_id,
            published=a.published,
        )

    # 4. Print CLI dashboard
    notifier.print_dashboard(analysed)

    # 5. Send alerts
    sent = await notifier.send_alerts(analysed)

    elapsed = time.monotonic() - start
    logger.info(
        "═══ Cycle done: %d new, %d alerted, %.1fs ═══",
        len(analysed),
        sent,
        elapsed,
    )
    return sent


async def run_loop():
    """Main agent loop — runs cycles on the configured interval."""
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("🚀 News Intelligence Agent started (poll every %ds)", config.POLL_INTERVAL_SECONDS)
    logger.info("   RSS feeds: %d", len(config.RSS_FEEDS))
    logger.info("   NewsAPI: %s", "enabled" if config.NEWS_API_KEY else "disabled")
    logger.info("   Telegram: %s", "enabled" if config.TELEGRAM_BOT_TOKEN else "disabled")
    if config.GEMINI_API_KEY:
        logger.info("   LLM: Gemini %s (FREE)", config.GEMINI_MODEL)
    elif config.OPENAI_API_KEY:
        logger.info("   LLM: OpenAI %s (paid)", config.OPENAI_MODEL)
    else:
        logger.info("   LLM: heuristic mode (no API key)")
    logger.info("   Min priority: %d", config.MIN_PRIORITY_SCORE)

    while _running:
        try:
            await run_cycle()
        except Exception:
            logger.exception("Cycle failed — will retry next interval")

        if not _running:
            break

        logger.info("Sleeping %ds until next cycle…", config.POLL_INTERVAL_SECONDS)
        # Sleep in small increments so we can respond to signals
        for _ in range(config.POLL_INTERVAL_SECONDS):
            if not _running:
                break
            await asyncio.sleep(1)

    database.close()
    logger.info("Agent stopped.")


# ── CLI: Show Dashboard from DB ──────────────────────────────────────────────

def show_dashboard():
    """Display recent articles from the database."""
    rows = database.get_recent(20)
    if not rows:
        print("No articles in database yet. Run the agent first.")
        return

    articles = [
        analyzer.AnalysedArticle(
            title=r["title"],
            url=r["url"] or "",
            source=r["source"] or "",
            published=r["published"] or "",
            hash=r["hash"],
            summary=r["summary"] or "",
            tags=(r["tags"] or "").split(","),
            priority=r["priority"] or 0,
            cluster_id=r["cluster_id"] or "",
        )
        for r in rows
    ]
    notifier.print_dashboard(articles)


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Real-Time News Intelligence Agent")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("--dashboard", action="store_true", help="Show recent alerts")
    args = parser.parse_args()

    if args.dashboard:
        show_dashboard()
    elif args.once:
        asyncio.run(run_cycle())
    else:
        asyncio.run(run_loop())


if __name__ == "__main__":
    main()
