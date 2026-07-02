# Phase 2 Build Prompt for Claude Code

Read the file `VALUE-INVESTOR-PHASE2-SPEC.md` — it contains the full specification for Phase 2 of the Value Investor Intelligence System.

**Context:** Phase 1 is already built and working (Flask + React app with Graham/Fisher/Valuation analysis). The problem is it relies entirely on the FMP free API which limits us to ~35 analyses per day, only 5 years of history, and a hardcoded list of ~220 stocks.

Phase 2 adds a local data pipeline using SEC EDGAR + yfinance + SQLite so the system can:
- Store financial data locally (no API calls after initial fetch)
- Access every US public company via SEC EDGAR (not just 220)
- Get 10+ years of history (EDGAR has decades of data)
- Pre-compute Graham/Fisher scores for instant screening
- Filter stocks by scores, signals, discount to intrinsic value

**Build this step by step following the 7-step order in the spec.**

Start with **Step 1** (database setup). Create the `database/` module with SQLite schema and helper functions. Test that the database initializes correctly and basic CRUD operations work.

**Important constraints:**
- This is a Windows machine. Use `py` instead of `python` for running scripts.
- Don't break any existing functionality — the current FMP-based flow should keep working as a fallback.
- The existing analysis engines (`analysis/graham.py`, `analysis/fisher.py`, `analysis/valuation.py`, `analysis/backtest.py`) should NOT be rewritten. They work fine. Just feed them data from the local DB instead of from FMP API responses. You may need to adjust the data format slightly so the dicts match what the analysis functions expect.
- Test each step before moving on. Ask me before proceeding to the next step.
