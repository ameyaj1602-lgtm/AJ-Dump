"""
AJ's Personal Voice Assistant
==============================
A voice agent that can help with tasks, answer questions,
and have natural conversations — via phone or web browser.

Powered by: OpenAI Realtime API + LiveKit Agents
"""

import logging
from livekit import agents, rtc
from livekit.agents import AgentSession, AutoSubscribe, cli, RoomInputOptions
from livekit.agents.llm import ChatContext, ChatMessage
from livekit.agents.voice import AgentTranscriptionOptions
from livekit.plugins import openai, silero


logger = logging.getLogger("voice-agent")
logger.setLevel(logging.INFO)


class VoiceAssistant:
    """Your personal voice assistant configuration."""

    # ---- Customize your assistant here ---- #

    AGENT_NAME = "AJ Assistant"

    INSTRUCTIONS = """
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
    """

    VOICE = "shimmer"  # Options: alloy, echo, fable, onyx, nova, shimmer

    # --------------------------------------- #


async def entrypoint(ctx: agents.JobContext):
    """Main entry point — runs when someone connects (phone or web)."""

    # Wait for the user to connect
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    logger.info(f"User connected to room: {ctx.room.name}")

    # Set up the AI model (OpenAI Realtime for ultra-low latency voice)
    model = openai.realtime.RealtimeModel(
        instructions=VoiceAssistant.INSTRUCTIONS,
        voice=VoiceAssistant.VOICE,
        temperature=0.8,
        modalities=["audio", "text"],
        turn_detection=openai.realtime.ServerVadOptions(
            threshold=0.5,
            prefix_padding_ms=300,
            silence_duration_ms=500,
        ),
    )

    # Create the agent session
    session = AgentSession(
        vad=silero.VAD.load(),  # Voice Activity Detection (knows when you stop talking)
        turn_detection="server",
    )

    # Start the session
    await session.start(
        room=ctx.room,
        agent=model,
        room_input_options=RoomInputOptions(
            noise_cancellation=agents.noise_cancellation.BVC(),
        ),
    )

    # Greet the user
    await session.say(
        "Hey there! I'm AJ Assistant. How can I help you today?",
        allow_interruptions=True,
    )


if __name__ == "__main__":
    cli.run_app(
        agents.WorkerOptions(
            entrypoint_fnc=entrypoint,
            # Agent will auto-join any new room
            auto_subscribe=AutoSubscribe.AUDIO_ONLY,
        ),
    )
