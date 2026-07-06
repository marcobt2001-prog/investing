# Build: LLM Qualitative Evaluation Module

Read the file `VALUE-INVESTOR-LLM-EVAL-SPEC.md` — it contains the full spec for adding an AI-powered qualitative evaluation layer to the Value Investor Intelligence System.

This module sends a company's financial data to an LLM (Claude API or a local Ollama model) and gets back a structured assessment covering competitive position (Porter's Five Forces / moat analysis), earnings quality, capital allocation, growth outlook, and risk assessment. It's designed as a pluggable system — the same prompt works with any provider.

**Build this step by step following the 7-step order in the spec.**

Start with **Step 1** (LLM provider infrastructure). Create the `llm/` directory under `backend/`, implement the config, abstract provider, Claude provider (using the `anthropic` Python SDK), and Ollama provider. Add `anthropic` to requirements.txt. Test that both providers can be instantiated and report their availability — Claude should work with an API key, Ollama should gracefully return `available: false` if it's not running.

**Important constraints:**
- Windows machine, use `py` not `python`.
- Don't modify existing analysis engines or ingestion code. The LLM module is purely additive — it reads from the database but doesn't change how anything else works.
- The LLM evaluation is ALWAYS on-demand (user clicks a button), never automatic during ingestion. It's too slow and costs money per call.
- For the Claude provider, use the `anthropic` Python SDK (not raw HTTP requests). Model should default to `claude-sonnet-4-6`.
- For JSON parsing of LLM responses: be defensive. Strip markdown code fences, handle partial JSON, return clear errors with the raw response if parsing fails. Low temperature (0.3) for consistency.
- The evaluation prompt asks for ONLY JSON output — no buy/sell recommendations, no stock price predictions. Just business quality analysis grounded in the financial data.
- Store evaluations in the database so they're cached. Only re-run if the user explicitly requests it (force=true).
- Use recharts for any charts if needed (already a frontend dependency).
- Test each step before moving on. Ask me before proceeding to the next step.
