# AJ Assistant - Voice Agent

A personal voice assistant you can talk to via **phone** or **web browser**.

Built with [LiveKit Agents](https://docs.livekit.io/agents/) + [OpenAI Realtime API](https://platform.openai.com/docs/guides/realtime).

---

## Quick Start (15 minutes)

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

### Step 2: Set Up Your Environment

```bash
# 1. Install Python (if you don't have it)
# Download from: https://www.python.org/downloads/
# Make sure to check "Add Python to PATH" during install

# 2. Clone this repo (or download it)
git clone https://github.com/ameyaj1602-lgtm/aj-dump.git
cd aj-dump

# 3. Create a virtual environment
python -m venv venv

# 4. Activate it
# On Mac/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

# 5. Install dependencies
pip install -r requirements.txt
```

### Step 3: Add Your API Keys

```bash
# Copy the example env file
cp .env.example .env

# Open .env in any text editor and paste your keys
# On Mac: open .env
# On Windows: notepad .env
```

Fill in these values in `.env`:
```
OPENAI_API_KEY=sk-your-actual-key
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your-key
LIVEKIT_API_SECRET=your-secret
```

### Step 4: Run the Agent

```bash
python agent.py dev
```

You should see: `Agent started successfully` in the terminal.

---

## Using the Web Interface

1. Make sure the agent is running (`python agent.py dev`)
2. Go to https://cloud.livekit.io
3. Open your project > **Playground**
4. Click **Connect** — you'll hear the assistant greet you!

**Or** open `web/index.html` in your browser for a custom interface.

---

## Adding Phone Calls (Optional)

To let people call a real phone number and talk to your agent:

### Step 1: Set Up Twilio

1. Sign up at https://www.twilio.com
2. Buy a phone number ($1/month)
3. Add your Twilio credentials to `.env`

### Step 2: Connect Twilio to LiveKit

1. In LiveKit Cloud, go to **Settings > SIP**
2. Follow the guide to create a SIP Trunk
3. Point your Twilio number to the LiveKit SIP endpoint
4. Full guide: https://docs.livekit.io/agents/quickstarts/sip-telephony/

Now people can call your Twilio number and talk to AJ Assistant!

---

## Customizing Your Agent

Open `agent.py` and edit the `VoiceAssistant` class:

```python
class VoiceAssistant:
    AGENT_NAME = "AJ Assistant"     # Change the name
    INSTRUCTIONS = "..."             # Change the personality & knowledge
    VOICE = "shimmer"                # Change the voice
```

**Available voices:** `alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer`

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` again |
| Agent won't start | Check that `.env` has all keys filled in |
| No audio in browser | Allow microphone access when prompted |
| "Connection failed" on web | Make sure agent is running first |

---

## Cost Estimates

- **LiveKit Cloud**: Free tier includes 50 GB bandwidth/month
- **OpenAI Realtime API**: ~$0.06/min for audio input + ~$0.24/min for audio output
- **Twilio** (optional): ~$1/month for number + ~$0.02/min for calls

A typical 5-minute conversation costs roughly $1.50 in API fees.

---

## Project Structure

```
aj-dump/
├── agent.py           # The voice agent (main file)
├── requirements.txt   # Python packages needed
├── .env.example       # Template for API keys
├── .env               # Your actual API keys (not in git)
├── web/
│   └── index.html     # Browser interface
└── README.md          # This file
```
