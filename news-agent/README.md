# Real-Time News Intelligence Agent

AI-powered news agent that fetches, analyses, ranks, and alerts you about breaking news faster than traditional platforms.

## Features

- **Multi-source ingestion** — RSS feeds (Google News, TechCrunch, Reuters, Economic Times, HN) + NewsAPI
- **LLM-powered analysis** — 1-line summaries, priority scoring (0–100), topic tagging, clustering
- **Heuristic fallback** — works without an API key using keyword-based scoring
- **Telegram alerts** — instant notifications with priority colour coding
- **Deduplication** — SHA-256 hashing prevents re-processing
- **SQLite storage** — lightweight, zero-config persistence
- **CLI dashboard** — clean terminal view of latest alerts
- **Async I/O** — concurrent feed fetching via httpx

## Quick Start

### 1. Install dependencies

```bash
cd news-agent
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your keys (see below)
```

### 3. Run

```bash
# Continuous loop (default: every 2 minutes)
python main.py

# Single cycle
python main.py --once

# View stored articles
python main.py --dashboard
```

## Configuration

Edit `.env` to set:

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | No | Enables LLM summaries/scoring. Without it, heuristic mode is used. |
| `OPENAI_MODEL` | No | Default: `gpt-4o-mini`. Any OpenAI-compatible model works. |
| `OPENAI_BASE_URL` | No | Swap providers (e.g. Ollama: `http://localhost:11434/v1`) |
| `NEWS_API_KEY` | No | Free at [newsapi.org](https://newsapi.org/register) |
| `TELEGRAM_BOT_TOKEN` | No | From [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | No | Your Telegram chat ID |
| `PRIORITY_KEYWORDS` | No | Comma-separated keywords that boost score |
| `FILTER_KEYWORDS` | No | If set, only matching articles are forwarded |
| `MIN_PRIORITY_SCORE` | No | Minimum score (0–100) to trigger alert. Default: 30 |
| `POLL_INTERVAL_SECONDS` | No | Default: 120 |

### Telegram Setup

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token
2. Start a chat with your new bot
3. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your `chat_id`

## Running on Android (Termux)

```bash
pkg install python
pip install -r requirements.txt
cp .env.example .env
nano .env  # add your keys
python main.py
```

To keep it running in the background:
```bash
nohup python main.py > agent.log 2>&1 &
```

## Using a Local LLM (Ollama)

Set in `.env`:
```
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama
OPENAI_MODEL=llama3
```

## Extending to Web/Mobile

The codebase is modular by design:

- **REST API**: Wrap `run_cycle()` and `database.get_recent()` with FastAPI/Flask
- **WebSocket**: Stream new alerts in real-time to a frontend
- **Mobile**: Use the REST API from React Native / Flutter
- **Web dashboard**: Query the SQLite DB or expose via API

Example FastAPI wrapper:
```python
from fastapi import FastAPI
import database, main as agent
import asyncio

app = FastAPI()

@app.get("/articles")
def get_articles(limit: int = 20):
    return database.get_recent(limit)

@app.post("/trigger")
async def trigger_cycle():
    count = await agent.run_cycle()
    return {"alerts_sent": count}
```

## Architecture

```
main.py        → Agent loop, CLI entry point
fetcher.py     → RSS + NewsAPI ingestion (async)
analyzer.py    → LLM analysis + heuristic fallback + filtering
notifier.py    → Telegram alerts + CLI dashboard
database.py    → SQLite storage + deduplication
config.py      → Environment-based configuration
```
