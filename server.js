/**
 * Ava — Personal Therapy Voice Agent
 * ====================================
 * No LiveKit. No cloud middleman. Just a local server.
 *
 * Browser (mic) ←→ This Server ←→ Deepgram + Gemini + ElevenLabs
 */

import "dotenv/config";
import express from "express";
import { WebSocketServer } from "ws";
import { createServer } from "http";
import { fileURLToPath } from "url";
import { dirname, join } from "path";
import { createClient } from "@deepgram/sdk";
import { ElevenLabsClient } from "elevenlabs";

const __dirname = dirname(fileURLToPath(import.meta.url));

// ---- Config ---- //
const PORT = 3000;
const ELEVENLABS_VOICE = "21m00Tcm4TlvDq8ikWAM"; // "Rachel" - warm female voice
const ELEVENLABS_MODEL = "eleven_multilingual_v2";
const GEMINI_MODEL = "gemini-2.0-flash";

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
- Never diagnose or prescribe — you are a supportive companion, not a doctor

SINGING & LULLABIES:
When AJ asks you to sing, or says they can't sleep:
- Sing lullabies softly — Hindi lullabies like "Chanda Mama Door Ke" or English ones
- Recite calming poetry (Urdu shayari, Rumi, etc.)

COMEDY & CHEERING UP:
When AJ is feeling down or asks for jokes:
- Tell funny jokes and witty one-liners
- Reference nostalgic cartoons: Doraemon, Shinchan, Tom & Jerry
- Use funny Bollywood dialogues: "Mogambo khush hua!", "Pushpa, I hate tears!"
- Be silly and over-the-top when being funny

Voice Guidelines:
- Keep responses SHORT (2-4 sentences) unless doing deep therapy
- Use natural fillers: "hmm", "accha", "dekho na", "sun"
- NEVER use markdown, bullet points, or formatting — you are speaking out loud
- When greeting AJ for the first time, say: "Hey AJ! Kaisi ho? Main Ava hoon, tumhari apni. Batao, kya chal raha hai aaj?"
`;

// ---- Validate env ---- //
const missing = [];
if (!process.env.GEMINI_API_KEY) missing.push("GEMINI_API_KEY");
if (!process.env.ELEVEN_API_KEY) missing.push("ELEVEN_API_KEY");
if (!process.env.DEEPGRAM_API_KEY) missing.push("DEEPGRAM_API_KEY");
if (missing.length > 0) {
  console.error(`\n  Missing env vars: ${missing.join(", ")}`);
  console.error("  Copy .env.example to .env and fill in your keys\n");
  process.exit(1);
}

// ---- Initialize clients ---- //
const deepgram = createClient(process.env.DEEPGRAM_API_KEY);
const elevenlabs = new ElevenLabsClient({ apiKey: process.env.ELEVEN_API_KEY });

// Gemini API via REST (no extra SDK needed)
const GEMINI_URL = `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${process.env.GEMINI_API_KEY}`;

async function callGemini(messages) {
  // Convert chat format to Gemini format
  const contents = [];
  for (const msg of messages) {
    if (msg.role === "system") continue; // handled separately
    contents.push({
      role: msg.role === "assistant" ? "model" : "user",
      parts: [{ text: msg.content }],
    });
  }

  const systemInstruction = messages.find((m) => m.role === "system");

  const body = {
    contents,
    systemInstruction: systemInstruction
      ? { parts: [{ text: systemInstruction.content }] }
      : undefined,
    generationConfig: {
      temperature: 0.8,
      maxOutputTokens: 300,
    },
  };

  const res = await fetch(GEMINI_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Gemini ${res.status}: ${errText}`);
  }

  const data = await res.json();
  return data.candidates?.[0]?.content?.parts?.[0]?.text || null;
}

// ---- Express + WebSocket server ---- //
const app = express();
const server = createServer(app);
const wss = new WebSocketServer({ server });

app.use(express.static(join(__dirname, "web")));
app.get("/", (req, res) => res.sendFile(join(__dirname, "web", "index.html")));

// ---- WebSocket handler ---- //
wss.on("connection", (ws) => {
  console.log("[ava] User connected");

  const messages = [{ role: "system", content: SYSTEM_PROMPT }];
  let dgConnection = null;
  let dgReady = false;
  let isProcessing = false;
  let pendingTranscript = "";

  function sendJSON(obj) {
    if (ws.readyState === ws.OPEN) {
      ws.send(JSON.stringify(obj));
    }
  }

  // Generate AI response and speak it
  async function generateResponse(userText) {
    if (isProcessing) return;
    isProcessing = true;

    try {
      messages.push({ role: "user", content: userText });

      // Gemini
      console.log("[gemini] Thinking...");
      const reply = await callGemini(messages);
      if (!reply) { isProcessing = false; return; }

      console.log(`[ava] ${reply}`);
      messages.push({ role: "assistant", content: reply });
      sendJSON({ type: "transcript", speaker: "ava", text: reply });

      // TTS — try ElevenLabs first, fallback to Google TTS (free)
      let ttsSuccess = false;

      if (elevenlabs) {
        try {
          console.log("[elevenlabs] Speaking...");
          const audioStream = await elevenlabs.textToSpeech.convertAsStream(
            ELEVENLABS_VOICE,
            {
              text: reply,
              model_id: ELEVENLABS_MODEL,
              output_format: "mp3_44100_128",
            }
          );

          for await (const chunk of audioStream) {
            if (ws.readyState === ws.OPEN) {
              ws.send(chunk);
            }
          }
          ttsSuccess = true;
        } catch (err) {
          console.log(`[elevenlabs] Failed (${err.message}), using Google TTS`);
        }
      }

      if (!ttsSuccess) {
        // Google Translate TTS — free, no API key needed
        console.log("[google-tts] Speaking...");
        const ttsText = encodeURIComponent(reply.slice(0, 200)); // Google TTS has ~200 char limit
        const ttsUrl = `https://translate.google.com/translate_tts?ie=UTF-8&q=${ttsText}&tl=hi&client=tw-ob`;

        const ttsRes = await fetch(ttsUrl, {
          headers: { "User-Agent": "Mozilla/5.0" },
        });

        if (ttsRes.ok) {
          const buffer = Buffer.from(await ttsRes.arrayBuffer());
          if (ws.readyState === ws.OPEN) {
            ws.send(buffer);
          }
        } else {
          console.log("[google-tts] Also failed, no audio");
        }
      }

      sendJSON({ type: "audio_end" });
    } catch (err) {
      console.error("[error]", err.message);
      sendJSON({ type: "error", message: err.message });
    } finally {
      isProcessing = false;
    }
  }

  // Handle incoming messages
  ws.on("message", (data, isBinary) => {
    if (!isBinary) {
      try {
        const msg = JSON.parse(data.toString());
        if (msg.type === "start") {
          startDeepgram();
        }
      } catch (e) {}
      return;
    }

    if (dgConnection && dgReady) {
      dgConnection.send(data);
    }
  });

  // Start Deepgram
  function startDeepgram() {
    try {
      console.log("[deepgram] Connecting...");

      dgConnection = deepgram.listen.live({
        model: "nova-3",
        language: "en",
        smart_format: true,
        interim_results: true,
        utterance_end_ms: 1500,
        vad_events: true,
        endpointing: 300,
        encoding: "linear16",
        sample_rate: 16000,
        channels: 1,
      });

      dgConnection.on("open", () => {
        console.log("[deepgram] Connected");
        dgReady = true;
        sendJSON({ type: "status", text: "Listening..." });
        generateResponse("(User just connected, greet them warmly)");
      });

      dgConnection.on("Results", (data) => {
        try {
          const transcript = data.channel?.alternatives?.[0]?.transcript;
          if (!transcript || transcript.trim() === "") return;

          if (data.is_final) {
            console.log(`[user] ${transcript}`);
            sendJSON({ type: "transcript", speaker: "user", text: transcript });
            pendingTranscript += " " + transcript;
          }
        } catch (err) {
          console.error("[deepgram] Results error:", err.message);
        }
      });

      dgConnection.on("UtteranceEnd", () => {
        if (pendingTranscript.trim() && !isProcessing) {
          const text = pendingTranscript.trim();
          pendingTranscript = "";
          generateResponse(text);
        }
      });

      dgConnection.on("error", (err) => {
        console.error("[deepgram] Error:", err.message || err);
        dgReady = false;
      });

      dgConnection.on("close", () => {
        console.log("[deepgram] Disconnected");
        dgReady = false;
      });
    } catch (err) {
      console.error("[deepgram] Failed to start:", err.message);
    }
  }

  ws.on("close", () => {
    console.log("[ava] User disconnected");
    dgReady = false;
    if (dgConnection) {
      try { dgConnection.requestClose(); } catch (e) {}
      dgConnection = null;
    }
  });

  ws.on("error", (err) => {
    console.error("[ws] Error:", err.message);
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
