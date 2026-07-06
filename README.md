# Magicpin Vera AI Challenge - Antigravity Bot

This is a FastAPI-based AI assistant bot built for the Magicpin Vera Challenge. It deterministically selects triggers based on urgency and time sensitivity, and uses an LLM (Gemini 1.5 Pro) with strict templating to generate grounded messages that respect category constraints.

## Architecture

- **bot.py**: The main FastAPI application. Uses in-memory dictionaries for context and conversational states to remain stateless for disk.
- **composer.py**: The generation core. Calls `google.generativeai` with a strict zero-temperature prompt. Implements a post-generation lint pass to catch URLs, multiple CTAs, taboo words, and repetitions.
- **conversation_handlers.py**: Contains heuristics to detect intent transitions ("let's do it"), auto-reply loops, and hostility.

## Tradeoffs

- **In-Memory Storage**: Contexts are stored in-memory. This enables lightning-fast retrievals for the `/v1/tick` endpoint but requires the server to not restart during the 60-min window.
- **LLM Fallback**: If the API key is not present or the LLM timeouts, the bot gracefully falls back to deterministic rule-based string templates to ensure 100% response rate within the 30-second budget.

## Running

1. `pip install -r requirements.txt`
2. `export GEMINI_API_KEY=your_key`
3. `uvicorn bot:app --host 0.0.0.0 --port 8080`
