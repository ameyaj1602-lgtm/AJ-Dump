/**
 * AJ's Personal Voice Assistant
 * ==============================
 * A voice agent built with Node.js that can help with tasks,
 * answer questions, and have natural conversations.
 *
 * Powered by: OpenAI Realtime API + LiveKit Agents
 */

import "dotenv/config";
import { cli, voice, WorkerOptions } from "@livekit/agents";
import * as openai from "@livekit/agents-plugin-openai";
import { fileURLToPath } from "node:url";

// ---- Customize your assistant here ---- //

const INSTRUCTIONS = `
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
`;

const VOICE = "shimmer"; // Options: alloy, echo, fable, onyx, nova, shimmer

// --------------------------------------- //

export default {
  entry: async (ctx) => {
    await ctx.connect();

    console.log(`[voice-agent] User connected to room: ${ctx.room.name}`);

    const model = new openai.realtime.RealtimeModel({
      voice: VOICE,
      modalities: ["audio", "text"],
    });

    const agent = new voice.Agent({
      instructions: INSTRUCTIONS,
      llm: model,
    });

    const session = new voice.AgentSession({
      llm: model,
    });

    await session.start({
      room: ctx.room,
      agent,
    });

    await session.say("Hey there! I'm AJ Assistant. How can I help you today?", {
      allowInterruptions: true,
    });
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
