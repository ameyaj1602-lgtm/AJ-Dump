# Noor — AJ's Therapy Voice Agent

A warm, empathetic AI companion that listens, guides, sings lullabies, tells jokes, and does character voices.

**Stack:**
- **Ears**: Deepgram Nova-3 (speech-to-text)
- **Brain**: OpenAI GPT-4o (thinking)
- **Voice**: ElevenLabs (text-to-speech — expressive, warm, can sing)
- **Orchestration**: LiveKit Agents

---

## Quick Start

### Step 1: Get Your API Keys (all have free tiers)

| Service | What it does | Sign up |
|---------|-------------|---------|
| **OpenAI** | Brain (GPT-4o) | https://platform.openai.com/api-keys |
| **ElevenLabs** | Voice (warm TTS, singing) | https://elevenlabs.io |
| **Deepgram** | Ears (STT, $200 free!) | https://console.deepgram.com |
| **LiveKit** | Connects everything | https://cloud.livekit.io |

### Step 2: Set Up

```bash
git clone https://github.com/ameyaj1602-lgtm/aj-dump.git
cd aj-dump
git checkout claude/voice-agent-setup-Xl1L7
npm install
cp .env.example .env
```

### Step 3: Add Keys to `.env`

```
OPENAI_API_KEY=sk-your-key
ELEVEN_API_KEY=your-elevenlabs-key
DEEPGRAM_API_KEY=your-deepgram-key
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your-key
LIVEKIT_API_SECRET=your-secret
```

### Step 4: Run

```bash
npm run dev
```

### Step 5: Talk to Noor

Go to https://agents-playground.livekit.io → Connect → Start talking!

---

## What Noor Can Do

- **Therapy & Support** — listens, validates feelings, guides gently
- **Sing Lullabies** — "Noor, mujhe neend nahi aa rahi" → sings for you
- **Tell Jokes** — Bollywood dialogues, cartoon references, silly voices
- **Motivate** — morning motivation, accountability, celebrates wins

---

## Customizing

Edit `agent.js`:
- Change `INSTRUCTIONS` to modify personality
- Change `ELEVENLABS_VOICE` to use a different voice
- Browse voices at https://elevenlabs.io/voice-library

---

## Cost Estimates

- **Deepgram**: $200 free credit (~400+ hours of listening)
- **ElevenLabs**: 10,000 credits/month free (~10 min audio)
- **OpenAI GPT-4o**: ~$0.01 per conversation turn
- **LiveKit**: Free tier (50 GB/month)
