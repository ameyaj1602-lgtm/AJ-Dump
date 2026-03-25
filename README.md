# AJ Assistant - Voice Agent (Node.js)

A personal voice assistant you can talk to via **phone** or **web browser**.

Built with [LiveKit Agents (Node.js)](https://docs.livekit.io/agents/) + [OpenAI Realtime API](https://platform.openai.com/docs/guides/realtime).

---

## Quick Start

### Step 1: Get Your API Keys

You need two accounts (both have free tiers):

1. **OpenAI** — Powers the AI brain and voice
   - Go to https://platform.openai.com/api-keys
   - Click "Create new secret key"
   - Copy the key (starts with `sk-`)

2. **LiveKit Cloud** — Handles real-time audio streaming
   - Go to https://cloud.livekit.io and sign up
   - Create a new project
   - Go to **Settings > Keys**
   - Copy your **URL**, **API Key**, and **API Secret**

### Step 2: Install Node.js

Download and install Node.js (v18 or higher) from: https://nodejs.org

Verify it's installed:
```bash
node --version   # Should show v18.x.x or higher
npm --version    # Should show 9.x.x or higher
```

### Step 3: Set Up the Project

```bash
# 1. Clone this repo (or download it)
git clone https://github.com/ameyaj1602-lgtm/aj-dump.git
cd aj-dump

# 2. Install dependencies
npm install

# 3. Copy the env template
cp .env.example .env
```

### Step 4: Add Your API Keys

Open `.env` in any text editor and paste your keys:

```
OPENAI_API_KEY=sk-your-actual-key
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your-key
LIVEKIT_API_SECRET=your-secret
```

### Step 5: Run the Agent

```bash
npm run dev
```

You should see `Agent started successfully` in the terminal.

---

## Talk to Your Agent

### Option A: LiveKit Playground (Easiest)
1. Make sure the agent is running (`npm run dev`)
2. Go to https://cloud.livekit.io
3. Open your project > **Playground**
4. Click **Connect** — you'll hear the assistant greet you!

### Option B: Custom Web Interface
Open `web/index.html` in your browser.

---

## Adding Phone Calls (Optional)

1. Sign up at https://www.twilio.com
2. Buy a phone number ($1/month)
3. Add your Twilio credentials to `.env`
4. In LiveKit Cloud, go to **Settings > SIP** and create a SIP Trunk
5. Full guide: https://docs.livekit.io/agents/quickstarts/sip-telephony/

---

## Customizing Your Agent

Open `agent.js` and edit the `AGENT_CONFIG` object:

```javascript
const AGENT_CONFIG = {
  name: "AJ Assistant",       // Change the name
  instructions: "...",         // Change the personality & knowledge
  voice: "shimmer",            // Change the voice
  greeting: "Hey there!...",   // Change the greeting
};
```

**Available voices:** `alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer`

---

## Project Structure

```
aj-dump/
├── agent.js           # The voice agent (main file)
├── package.json       # Node.js dependencies
├── .env.example       # Template for API keys
├── .env               # Your actual API keys (not in git)
├── web/
│   └── index.html     # Browser interface
└── README.md          # This file
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `MODULE_NOT_FOUND` | Run `npm install` again |
| Agent won't start | Check that `.env` has all keys filled in |
| No audio in browser | Allow microphone access when prompted |
| "Connection failed" on web | Make sure agent is running first |
| Node version error | Upgrade to Node.js v18+ from https://nodejs.org |

---

## Cost Estimates

- **LiveKit Cloud**: Free tier includes 50 GB bandwidth/month
- **OpenAI Realtime API**: ~$0.06/min for audio input + ~$0.24/min for audio output
- **Twilio** (optional): ~$1/month for number + ~$0.02/min for calls

A typical 5-minute conversation costs roughly $1.50 in API fees.
