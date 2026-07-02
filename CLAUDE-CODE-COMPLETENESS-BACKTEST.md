# Build: Data Completeness Scoring + Cross-Company Strategy Backtest

Read the file `VALUE-INVESTOR-COMPLETENESS-BACKTEST-SPEC.md` — it contains the full spec for two features:

1. **Data completeness scoring** — track which Graham/Fisher inputs were actually available vs missing for each company, report a completeness percentage, flag low-completeness companies in the screener and analysis views.

2. **Cross-company strategy backtest** — test the investment strategy across ALL companies in the database historically. The strategy is: buy companies with strong Graham + Fisher scores and growing IV trend, at a margin of safety, sell when they exceed intrinsic value. Compare against S&P 500 benchmark. Also run a parameter sweep across different margin-of-safety and sell-premium levels.

**Build this step by step following the 7-step order in the spec.**

Start with **Step 1** (data completeness in the Graham engine). Update `graham.py` to add a `dataAvailable` dict tracking which criteria had the required input data, plus a `dataCompleteness` ratio and `adjustedPctScore`. Do NOT change the actual scoring logic — just add the metadata alongside it. Test by running the scoring on a well-known company (AAPL) and a company you know has data gaps.

**Important constraints:**
- Windows machine, use `py` not `python`.
- The scoring functions (`score_graham`, `score_fisher`) should remain backward-compatible — existing code that calls them should not break. The new fields are purely additive.
- The `adjustedPctScore` divides total score by only the criteria that had data available. The regular `pctScore` and `grade` stay unchanged (conservative, counts missing data as failures).
- For the strategy backtest (Steps 5-6), you'll need to re-score companies historically using only data available at each point in time. Use the financials table filtered by fiscal_year and the historical_valuations table. The existing analysis engines (`score_graham`, `score_fisher`) take lists of income/balance/cashflow statements, so you just truncate the lists to only include years ≤ the backtest year.
- Make sure SPY is in the database for benchmark comparison. If it's not, auto-ingest it when the backtest runs.
- Use recharts for any charts (it's already a frontend dependency).
- Test each step before moving on. Ask me before proceeding to the next step.
