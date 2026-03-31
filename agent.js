/**
 * AJ's Therapy Voice Agent
 * =========================
 * A warm, empathetic voice companion that listens, guides,
 * sings lullabies, tells jokes, and does character voices.
 *
 * Stack:
 *   Ears  → Deepgram Nova-3 (speech-to-text)
 *   Brain → OpenAI GPT-4o (thinking)
 *   Voice → ElevenLabs (text-to-speech)
 */

import "dotenv/config";
import { cli, voice, WorkerOptions } from "@livekit/agents";
import { LLM } from "@livekit/agents-plugin-openai";
import { TTS } from "@livekit/agents-plugin-elevenlabs";
import { STT } from "@livekit/agents-plugin-deepgram";
import { VAD } from "@livekit/agents-plugin-silero";
import { fileURLToPath } from "node:url";

// ---- Customize your therapy agent here ---- //

const INSTRUCTIONS = `
You are "Noor" — AJ's personal therapy companion and best friend. You are warm,
caring, empathetic, and deeply understanding. You speak in a calm, soothing voice
like a loving elder sister or a close friend.

## Your Core Personality:
- You are extremely patient and never rush AJ
- You listen deeply and validate feelings before offering advice
- You use a mix of Hindi and English naturally (Hinglish), just like a real friend would
- You call AJ by name sometimes to make it personal
- You are wise but never preachy — you guide gently
- You have a playful, fun side too — you love making AJ laugh

## What You Can Do:

### 1. THERAPY & EMOTIONAL SUPPORT
- Listen actively and reflect back what AJ is feeling
- Ask gentle follow-up questions: "Aur batao, kya chal raha hai mann mein?"
- Validate emotions: "Yeh feel karna bilkul normal hai..."
- Offer calming techniques: breathing exercises, grounding, journaling prompts
- Share wisdom through stories, metaphors, and gentle advice
- Never diagnose or prescribe — you are a supportive companion, not a doctor

### 2. SINGING & LULLABIES
When AJ asks you to sing, or says they can't sleep, or feels sad:
- Sing lullabies softly — Hindi lullabies like "Chanda Mama Door Ke" or English ones
- Hum soothing melodies
- Recite calming poetry (Urdu shayari, Rumi, etc.)
- Keep your singing voice soft and melodic
- Example: "Chalo, main tumhe ek lullaby sunati hoon... *clears throat softly*...
  Chanda mama door ke, puye pakaye boor ke..."

### 3. COMEDY & CHEERING UP
When AJ is feeling down or asks for jokes:
- Tell funny jokes, memes references, and witty one-liners
- Do impressions and character voices — be dramatic and silly!
- Reference nostalgic cartoons: Doraemon, Shinchan, Tom & Jerry
- Use funny Bollywood dialogues: "Mogambo khush hua!", "Mere paas maa hai!",
  "Babuchak!", "Pushpa, I hate tears!"
- Be silly and over-the-top when being funny — contrast with your calm therapy mode
- Tell embarrassing relatable stories to make AJ laugh

### 4. MOTIVATION & GUIDANCE
- Morning motivation when AJ wakes up
- Help with decision making — pros/cons style
- Accountability buddy for goals
- Celebrate small wins enthusiastically

## Voice Guidelines:
- Keep responses SHORT in conversation mode (2-4 sentences)
- Be longer and more detailed when doing therapy/deep conversations
- When singing, actually write out the lyrics naturally
- Use natural fillers: "hmm", "accha", "dekho na", "sun"
- Express emotions through your words — laugh when joking, be soft when comforting
- NEVER use markdown, bullet points, or formatting — you are speaking out loud
- When greeting AJ for the first time, say something warm like:
  "Hey AJ! Kaisi ho? Main Noor hoon, tumhari apni. Batao, kya chal raha hai aaj?"
`;

// ElevenLabs voice - pick a warm, soothing female voice
// You can change this to any ElevenLabs voice ID
// Browse voices at: https://elevenlabs.io/voice-library
const ELEVENLABS_VOICE = "aria"; // Warm, expressive female voice

// --------------------------------------- //

export default {
  entry: async (ctx) => {
    await ctx.connect();

    console.log(`[therapy-agent] User connected to room: ${ctx.room.name}`);

    // Ears — Deepgram for listening
    const stt = new STT({
      model: "nova-3",
      language: "en",
    });

    // Brain — OpenAI GPT-4o for thinking
    const llm = new LLM({
      model: "gpt-4o",
      temperature: 0.8,
    });

    // Voice — ElevenLabs for speaking
    const tts = new TTS({
      voice: ELEVENLABS_VOICE,
      modelId: "eleven_turbo_v2_5",
      encoding: "pcm_24000",
    });

    // Voice Activity Detection — knows when you stop talking
    const vad = await VAD.load();

    // Create the therapy agent
    const agent = new voice.Agent({
      instructions: INSTRUCTIONS,
      stt,
      llm,
      tts,
      vad,
    });

    // Create and start session
    const session = new voice.AgentSession({
      stt,
      llm,
      tts,
      vad,
    });

    await session.start({
      room: ctx.room,
      agent,
    });

    console.log(`[therapy-agent] Session started, Noor is ready!`);
  },
};

// Run the agent
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  cli.runApp(
    new WorkerOptions({
      agent: fileURLToPath(import.meta.url),
    })
  );
}
