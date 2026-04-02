#!/usr/bin/env python3
"""
Real-Time News Intelligence Agent — Production Grade
─────────────────────────────────────────────────────
Fetches → Deduplicates → Analyses → Ranks → Alerts

Features:
  - Auto-recovery on crash with exponential backoff
  - DB cleanup for long-running operation
  - Never dies — outer restart loop catches everything

Usage:
    python main.py              # Run forever
    python main.py --once       # Run one cycle and exit
    python main.py --dashboard  # Show recent alerts from DB
"""

import argparse
import asyncio
import logging
import signal
import sys
import time
import traceback

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

# Quiet noisy libraries
for lib in ["httpx", "httpcore", "feedparser", "charset_normalizer", "hpack"]:
    logging.getLogger(lib).setLevel(logging.WARNING)


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

    # 3. Store in DB (only articles above threshold)
    stored = 0
    for a in analysed:
        ok = database.insert_article(
            article_hash=a.hash, title=a.title, url=a.url, source=a.source,
            summary=a.summary, tags=",".join(a.tags), priority=a.priority,
            cluster_id=a.cluster_id, published=a.published,
        )
        if ok:
            stored += 1

    # 4. Dashboard
    notifier.print_dashboard(analysed)

    # 5. Telegram alerts
    sent = await notifier.send_alerts(analysed)

    elapsed = time.monotonic() - start
    logger.info("═══ Done: %d new, %d stored, %d alerted, %.1fs ═══", len(analysed), stored, sent, elapsed)
    return sent


async def run_loop():
    """Main agent loop — runs forever with auto-recovery."""
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("🚀 News Intelligence Agent started")
    logger.info("   RSS feeds: %d | Poll: %ds | Min score: %d",
                len(config.RSS_FEEDS), config.POLL_INTERVAL_SECONDS, config.MIN_PRIORITY_SCORE)
    logger.info("   Gemini: %s | Telegram: %s",
                "on" if config.GEMINI_API_KEY else "off",
                "on" if config.TELEGRAM_BOT_TOKEN else "off")

    consecutive_failures = 0
    cycle_count = 0

    while _running:
        try:
            await run_cycle()
            consecutive_failures = 0
            cycle_count += 1

            # Periodic DB cleanup every 10 cycles
            if cycle_count % 10 == 0:
                deleted = database.cleanup_old(config.MAX_ARTICLE_AGE_HOURS)
                if deleted:
                    logger.info("DB cleanup: removed %d old articles", deleted)

        except Exception:
            consecutive_failures += 1
            backoff = min(2 ** consecutive_failures * 5, 300)
            logger.exception("Cycle failed (attempt %d) — retrying in %ds", consecutive_failures, backoff)
            for _ in range(backoff):
                if not _running:
                    break
                await asyncio.sleep(1)
            continue

        if not _running:
            break

        logger.info("Sleeping %ds until next cycle…", config.POLL_INTERVAL_SECONDS)
        for _ in range(config.POLL_INTERVAL_SECONDS):
            if not _running:
                break
            await asyncio.sleep(1)

    database.close()
    logger.info("Agent stopped.")


# ── CLI: Dashboard ────────────────────────────────────────────────────────────

def show_dashboard():
    rows = database.get_recent(50, min_priority=config.MIN_PRIORITY_SCORE)
    if not rows:
        print("No articles in database yet. Run the agent first.")
        return

    articles = [
        analyzer.AnalysedArticle(
            title=r["title"], url=r["url"] or "", source=r["source"] or "",
            published=r["published"] or "", hash=r["hash"],
            summary=r["summary"] or "", tags=(r["tags"] or "").split(","),
            priority=r["priority"] or 0, cluster_id=r["cluster_id"] or "",
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
        # Outer restart loop — truly never dies
        while True:
            try:
                asyncio.run(run_loop())
                break  # clean exit via signal
            except KeyboardInterrupt:
                break
            except Exception:
                logger.critical("Fatal crash — restarting in 60s\n%s", traceback.format_exc())
                time.sleep(60)


if __name__ == "__main__":
    main()
