# Magicpin Vera AI Challenge - Antigravity Bot

This repository contains the submission for the magicpin Vera AI Challenge. The bot is a stateful FastAPI HTTP server that acts as a deterministic, AI-powered conversational agent capable of orchestrating context-aware outreach to merchants.

## Approach & Architecture

We built a modular, stateful application prioritizing determinism, speed, and strict rubric adherence. The architecture comprises:

- **`bot.py`**: The FastAPI server exposing all 5 required endpoints (`/v1/healthz`, `/v1/metadata`, `/v1/context`, `/v1/tick`, `/v1/reply`). It safely handles in-memory context and state management.
- **`composer.py`**: The LLM engine. It parses the 4-layer context (Category, Merchant, Customer, Trigger) and instructs `gemini-3.5-flash` at temperature `0.0` to synthesize grounded responses. It also contains a robust fallback mechanism for rate-limit safety.
- **`conversation_handlers.py`**: The deterministic dialogue gatekeeper. It enforces strict ordering for edge cases: Hostility > Auto-Reply > Intent, guaranteeing the bot never hallucinates past a hostile merchant or gets trapped in auto-reply loops.

## Rubric Metrics & Implementation

We strictly designed the bot to maximize scores across the 5 evaluation dimensions:

1. **Decision Quality (/10)**
   - *Implementation:* We built explicit transition handlers. If a merchant is hostile, the bot explicitly transitions to `end`. If they ask for next steps, it transitions to `send`. We also prioritize time-sensitive triggers intelligently during the `/v1/tick` evaluation.
   
2. **Specificity (/10)**
   - *Implementation:* Our LLM system prompt uses hard data injection. Instead of generating generic filler, the bot forces the LLM to ground its response using `merchant.payload.offers` and precise names/metrics provided in the context pushes.

3. **Category Fit (/10)**
   - *Implementation:* The LLM is explicitly instructed to adopt the `tone` defined within the category payload (e.g., clinical for Dentists, high-energy for Gyms). 

4. **Merchant Fit (/10)**
   - *Implementation:* The `lint_response` function acts as a safety guardrail to ensure the generated output strictly adheres to merchant guidelines, blocking taboo words and ensuring personalization constraints are met.

5. **Engagement Compulsion (/10)**
   - *Implementation:* The prompt strictly demands a low-effort next action and a single, clear CTA. The linter enforces that multiple CTAs or generic URLs are stripped out or retried to keep the cognitive load on the merchant extremely low.

## Tradeoffs & Design Decisions

- **In-Memory Storage over Database:** To ensure lightning-fast responses (well under the 30s timeout) and stateless-disk compliance, we opted for purely in-memory Python dictionaries for state (`contexts`, `conversations`).
- **Graceful Fallbacks:** To ensure the judge simulator never crashes if the LLM hits a `429 Too Many Requests` limit on the free tier, we built `get_fallback_message()` which generates a deterministic, safe JSON payload that still adheres to the schema.
- **LLM Selection:** `gemini-3.5-flash` was selected for its incredible latency, reducing tick cycle times dramatically compared to heavier models while maintaining excellent instruction following.

## Running Locally

1. `pip install -r requirements.txt`
2. `export GEMINI_API_KEY="your_api_key"`
3. `uvicorn bot:app --host 0.0.0.0 --port 8080`
4. Run tests: `python3 judge_simulator.py`
