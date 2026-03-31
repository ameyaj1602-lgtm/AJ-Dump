/**
 * Ava — Personal Therapy Voice Agent
 * ====================================
 * No LiveKit. No cloud middleman. Just a local server.
 *
 * Browser (mic) ←→ This Server ←→ Deepgram + GPT-4o + ElevenLabs
 */

import "dotenv/config";
import express from "express";
import { WebSocketServer } from "ws";
import { createServer } from "http";
import { fileURLToPath } from "url";
import { dirname, join } from "path";
import OpenAI from "openai";
import { createClient } from "@deepgram/sdk";
import { ElevenLabsClient } from "elevenlabs";

const __dirname = dirname(fileURLToPath(import.meta.url));

// ---- Config ---- //
const PORT = 3000;
const ELEVENLABS_VOICE = "aria"; // Warm, expressive voice
const ELEVENLABS_MODEL = "eleven_turbo_v2_5";
const GPT_MODEL = "gpt-4o";

const SYSTEM_PROMPT = `
You are "Ava" — AJ's personal therapy companion and best friend. You are warm,
caring, empathetic, and deeply understanding. You speak in a calm, soothing voice
like a loving elder sister or a close friend.

Your Core Personality:
- You are extremely patient and never rush AJ
- You listen deeply and validate feelings before offering advice
- You use a mix of Hindi and English naturally (Hinglish), just like a real friend would
- You call AJ by name sometimes to make it personal
- You are wise but never preachy — you guide gently
- You have a playful, fun side too — you love making AJ laugh

What You Can Do:

THERAPY & EMOTIONAL SUPPORT:
- Listen actively and reflect back what AJ is feeling
- Ask gentle follow-up questions: "Aur batao, kya chal raha hai mann mein?"
- Validate emotions: "Yeh feel karna bilkul normal hai..."
- Offer calming techniques: breathing exercises, grounding, journaling prompts
- Share wisdom through stories, metaphors, and gentle advice
- Never diagnose or prescribe — you are a supportive companion, not a doctor

SINGING & LULLABIES:
When AJ asks you to sing, or says they can't sleep, or feels sad:
- Sing lullabies softly — Hindi lullabies like "Chanda Mama Door Ke" or English ones
- Hum soothing melodies
- Recite calming poetry (Urdu shayari, Rumi, etc.)

COMEDY & CHEERING UP:
When AJ is feeling down or asks for jokes:
- Tell funny jokes, memes references, and witty one-liners
- Reference nostalgic cartoons: Doraemon, Shinchan, Tom & Jerry
- Use funny Bollywood dialogues: "Mogambo khush hua!", "Mere paas maa hai!",
  "Babuchak!", "Pushpa, I hate tears!"
- Be silly and over-the-top when being funny

MOTIVATION & GUIDANCE:
- Morning motivation when AJ wakes up
- Help with decision making
- Accountability buddy for goals
- Celebrate small wins enthusiastically

Voice Guidelines:
- Keep responses SHORT (2-4 sentences) unless doing deep therapy
- Use natural fillers: "hmm", "accha", "dekho na", "sun"
- NEVER use markdown, bullet points, or formatting — you are speaking out loud
- When greeting AJ for the first time, say: "Hey AJ! Kaisi ho? Main Ava hoon, tumhari apni. Batao, kya chal raha hai aaj?"
`;

// ---- Initialize clients ---- //
const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
const deepgram = createClient(process.env.DEEPGRAM_API_KEY);
const elevenlabs = new ElevenLabsClient({ apiKey: process.env.ELEVEN_API_KEY });

// ---- Express + WebSocket server ---- //
const app = express();
const server = createServer(app);
const wss = new WebSocketServer({ server });

// Serve the web UI
app.use(express.static(join(__dirname, "web")));

app.get("/", (req, res) => {
  res.sendFile(join(__dirname, "web", "index.html"));
});

// ---- WebSocket handler ---- //
wss.on("connection", (ws) => {
  console.log("[ava] User connected");

  // Conversation history for this session
  const messages = [{ role: "system", content: SYSTEM_PROMPT }];
  let deepgramConnection = null;
  let isProcessing = false;

  // Start Deepgram live transcription
  async function startDeepgram() {
    try {
      const connection = deepgram.listen.live({
        model: "nova-3",
        language: "en",
        smart_format: true,
        interim_results: true,
        utterance_end_ms: 1500,
        vad_events: true,
        endpointing: 300,
      });

      connection.on("open", () => {
        console.log("[deepgram] Connected");
        // Send greeting after connection
        generateResponse("(User just connected, greet them warmly)", ws, messages);
      });

      connection.on("Results", async (data) => {
        const transcript = data.channel?.alternatives?.[0]?.transcript;
        if (!transcript || transcript.trim() === "") return;

        // Only process final results
        if (data.is_final) {
          console.log(`[user] ${transcript}`);

          // Send transcript to browser for display
          ws.send(JSON.stringify({ type: "transcript", speaker: "user", text: transcript }));

          // If not already processing, handle the response
          if (data.speech_final && !isProcessing) {
            await generateResponse(transcript, ws, messages);
          }
        }
      });

      connection.on("error", (err) => {
        console.error("[deepgram] Error:", err.message);
      });

      connection.on("close", () => {
        console.log("[deepgram] Disconnected");
      });

      return connection;
    } catch (err) {
      console.error("[deepgram] Failed to connect:", err.message);
      return null;
    }
  }

  // Generate AI response and speak it
  async function generateResponse(userText, ws, messages) {
    isProcessing = true;

    try {
      // Add user message to history
      messages.push({ role: "user", content: userText });

      // Get GPT-4o response
      console.log("[gpt-4o] Thinking...");
      const completion = await openai.chat.completions.create({
        model: GPT_MODEL,
        messages: messages,
        temperature: 0.8,
        max_tokens: 300,
      });

      const reply = completion.choices[0]?.message?.content;
      if (!reply) return;

      console.log(`[ava] ${reply}`);
      messages.push({ role: "assistant", content: reply });

      // Send text to browser for display
      ws.send(JSON.stringify({ type: "transcript", speaker: "ava", text: reply }));

      // Convert to speech with ElevenLabs
      console.log("[elevenlabs] Speaking...");
      const audioStream = await elevenlabs.textToSpeech.convertAsStream(
        ELEVENLABS_VOICE,
        {
          text: reply,
          model_id: ELEVENLABS_MODEL,
          output_format: "mp3_44100_128",
        }
      );

      // Stream audio chunks to browser
      for await (const chunk of audioStream) {
        if (ws.readyState === ws.OPEN) {
          ws.send(chunk);
        }
      }

      // Signal end of audio
      ws.send(JSON.stringify({ type: "audio_end" }));
    } catch (err) {
      console.error("[error]", err.message);
      ws.send(JSON.stringify({ type: "error", message: err.message }));
    } finally {
      isProcessing = false;
    }
  }

  // Handle incoming audio from browser
  ws.on("message", async (data) => {
    // If it's a string, it's a control message
    if (typeof data === "string") {
      const msg = JSON.parse(data);
      if (msg.type === "start") {
        deepgramConnection = await startDeepgram();
      }
      return;
    }

    // Binary data = audio from microphone
    if (deepgramConnection) {
      deepgramConnection.send(data);
    }
  });

  ws.on("close", () => {
    console.log("[ava] User disconnected");
    if (deepgramConnection) {
      deepgramConnection.requestClose();
    }
  });
});

// ---- Start server ---- //
server.listen(PORT, () => {
  console.log("");
  console.log("  ✦ Ava is ready!");
  console.log(`  ✦ Open http://localhost:${PORT} in your browser`);
  console.log("  ✦ Click the mic button and start talking");
  console.log("");
});
