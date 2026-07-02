# Phase 3 Build Prompt for Claude Code

Read the file `VALUE-INVESTOR-PHASE3-SPEC.md` — it contains the full specification for Phase 3 of the Value Investor Intelligence System.

**Context:** Phase 1 built the Flask + React app with Graham/Fisher/Valuation/Backtest analysis. Phase 2 replaced FMP with a local data pipeline (SEC EDGAR + yfinance + SQLite). The system currently has ~25 companies ingested with ~19 years of history each, and all analysis runs against the local database.

Phase 3 adds three capabilities:
1. **Industry-focused bulk ingestion** — discover all US companies, browse by industry, deep-ingest entire industries for real peer group analysis
2. **Intrinsic value trend tracking** — compute historical intrinsic values year-by-year to see if a company's value is growing or declining
3. **Valuation model accuracy by industry** — measure which model is most predictive per industry, use industry-specific weights instead of naive averages

**Build this step by step following the 7-step order in the spec.**

Start with **Step 1** (database schema updates). Add the two new tables (`historical_valuations`, `model_accuracy`), add new columns to `scores`, and add all the new helper functions to `models.py`. Test that the schema migrates cleanly without breaking existing data.

**Important constraints:**
- This is a Windows machine. Use `py` instead of `python` for running scripts.
- Don't modify the existing analysis engines (`graham.py`, `fisher.py`, `valuation.py`, `backtest.py`). Build new modules alongside them.
- The existing `db_adapter.py` translates DB rows to FMP-style format for the analysis engines. Continue using this pattern for any new analysis modules that need to call the existing engines.
- The database already has data in it from Phase 2 (~25 companies). Schema changes must not destroy existing data — use `ALTER TABLE` for adding columns, and `CREATE TABLE IF NOT EXISTS` for new tables.
- Test each step before moving on. Ask me before proceeding to the next step.
- When building the IV trends chart in the frontend (Step 6), use recharts — it's already available as a dependency.
