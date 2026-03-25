/**
 * AJ's Personal Voice Assistant
 * ==============================
 * A voice agent built with Node.js that can help with tasks,
 * answer questions, and have natural conversations.
 *
 * Powered by: OpenAI Realtime API + LiveKit Agents
 *
 * Usage:
 *   npm run dev     → development mode (auto-creates room)
 *   npm run start   → production mode
 */

require("dotenv").config();

const { WorkerOptions, cli, defineAgent, AutoSubscribe } = require("@livekit/agents");
const { RealtimeModel } = require("@livekit/agents-plugin-openai");
const { VAD } = require("@livekit/agents-plugin-silero");

// ---- Customize your assistant here ---- //

const AGENT_CONFIG = {
  name: "AJ Assistant",

  instructions: `
    You are AJ's friendly personal assistant. Your name is AJ Assistant.

    Your personality:
    - Warm, helpful, and conversational
    - You speak naturally, like a real person (use contractions, casual language)
    - Keep responses concise — this is a voice conversation, not a text chat
    - If you don't know something, say so honestly

    What you can help with:
    - Answering general knowledge questions
    - Brainstorming ideas
    - Giving advice and recommendations
    - Having casual conversations
    - Explaining complex topics in simple terms
    - Math, science, history, and more

    Important voice guidelines:
    - Keep answers SHORT (1-3 sentences) unless asked for detail
    - Don't use markdown, bullet points, or formatting — you're speaking out loud
    - Use natural pauses and conversational flow
    - If the user seems done talking, don't keep rambling
  `,

  voice: "shimmer", // Options: alloy, echo, fable, onyx, nova, shimmer

  greeting: "Hey there! I'm AJ Assistant. How can I help you today?",
};

// --------------------------------------- //

/**
 * Main entry point — runs when someone connects (phone or web).
 */
const voiceAgent = defineAgent({
  entry: async (ctx) => {
    // Wait for the user to connect
    await ctx.connect({ autoSubscribe: AutoSubscribe.AUDIO_ONLY });

    console.log(`[voice-agent] User connected to room: ${ctx.room.name}`);

    // Set up the AI model (OpenAI Realtime for ultra-low latency voice)
    const model = new RealtimeModel({
      instructions: AGENT_CONFIG.instructions,
      voice: AGENT_CONFIG.voice,
      temperature: 0.8,
      modalities: ["audio", "text"],
      turnDetection: {
        type: "server_vad",
        threshold: 0.5,
        prefixPaddingMs: 300,
        silenceDurationMs: 500,
      },
    });

    // Load Voice Activity Detection
    const vad = await VAD.load();

    // Create and start the agent session
    const session = await ctx.createAgentSession({
      vad,
      turnDetection: "server",
    });

    await session.start({
      room: ctx.room,
      agent: model,
    });

    // Greet the user
    await session.say(AGENT_CONFIG.greeting, {
      allowInterruptions: true,
    });
  },
});

// Run the agent
cli.runApp(
  new WorkerOptions({
    agent: voiceAgent,
    autoSubscribe: AutoSubscribe.AUDIO_ONLY,
  })
);
