# Value Investor Intelligence System

A local web application that screens, analyzes, and values publicly traded stocks using the investment principles of **Benjamin Graham** (*The Intelligent Investor*) and **Philip Fisher** (*Common Stocks and Uncommon Profits*).

## What It Does

- **Screener** — Filter every company in your local database by sector, industry, market cap, Graham/Fisher grade, valuation signal, discount to intrinsic value, and intrinsic-value trend. Pure SQL — no API calls, instant results. Export to CSV.
- **Industry Deep-Dive** — Browse companies by sub-industry, deep-ingest an entire industry for real peer-group analysis, and see per-industry valuation-model accuracy rankings.
- **Graham Analysis** — Scores stocks against 9 quantitative criteria from *The Intelligent Investor*
- **Fisher Checklist** — Evaluates 15 points from *Common Stocks and Uncommon Profits* (11 automated, 4 flagged for manual review)
- **Data Completeness Scoring** — Tracks which Graham/Fisher criteria actually had the required input data. A missing input (common for banks/insurers with non-classified balance sheets) is shown as "No data" rather than a failed test, and an *adjusted* score reflects only the criteria that could be evaluated. The screener flags low-completeness companies so you know when a score is unreliable — without hiding them.
- **Valuation Models** — Computes intrinsic value using 5 methods: Graham Formula, DCF, Book Value, Earnings Power Value, and NCAV
- **Intrinsic Value Trends** — Computes historical intrinsic value year-by-year so you can see whether a company's value is growing, flat, or declining — with a chart of each model + composite vs. the actual stock price over time.
- **Model Accuracy by Industry** — Measures which valuation model was most predictive of future prices for each industry, and blends models with industry-specific weights instead of a naive average.
- **Buy/Sell Signal** — Composite valuation with recommended buy prices at 25%, 35%, and 50% margin of safety
- **Single-Company Backtesting** — Simulates a Graham-style strategy over 10+ years of daily price history with configurable parameters
- **Cross-Company Strategy Backtest** — Tests the full value strategy across *every* company in the database, historically: each year it re-scores all companies using only data available at the time, buys quality names (Graham/Fisher B+ with growing intrinsic value) at a margin of safety, and sells when they exceed intrinsic value. Compares against the S&P 500 (SPY) benchmark and includes a parameter sweep across margin-of-safety and sell-premium levels.

## Architecture

The system runs entirely against a **local SQLite database** populated from free, authoritative sources:

- **SEC EDGAR** — financial statements (every US public company, 10+ years of history). No API key required.
- **yfinance** — prices, profiles, sector/industry classification. No API key required.
- **SQLite** — local persistent store. Pre-computes Graham, Fisher, and valuation scores at ingestion time so screening is instant.

After the initial bulk ingest, the app makes **zero external API calls** for screening or analysis. FMP remains supported as an optional fallback for tickers not yet in your database.

**Two-phase ingestion (Phase 3):**

- **Light ingest** — a fast, profile-only pass (name/sector/industry/market cap/price via one batched yfinance call, no EDGAR) that builds a browsable catalog of the whole US-listed universe. Used to populate the industry dropdowns.
- **Deep ingest** — the full pipeline (EDGAR financials + price history + all scores + historical intrinsic-value trends) for a selected industry or set of tickers.

After deep-ingesting an industry, the system computes **per-industry model accuracy**: for each company with enough history it compares each model's intrinsic-value estimate N years ago to the actual price today, aggregates the prediction errors by industry, and derives inverse-error blending weights. Book value, for example, ranks far more predictive for banks than for semiconductors.

## Setup

### 1. Backend (Python/Flask)

```bash
cd backend
pip install -r requirements.txt
```

Dependencies: Flask, Flask-CORS, requests, yfinance. SQLite is part of the Python standard library.

### 2. Frontend (React/Vite)

```bash
cd frontend
npm install
```

Frontend dependencies include **recharts** (used for the intrinsic-value trend chart).

### 3. Initial data ingest

Populate the local database with company data. **First run takes 30–60 minutes for 500 companies; subsequent use is instant.**

```bash
cd backend

# Quick start: 25 hand-picked blue chips across sectors (~1 minute)
py -m ingestion.bulk_ingest --universe starter

# Or the full S&P 500 (~30 minutes)
py -m ingestion.bulk_ingest --universe sp500

# Or a custom list
py -m ingestion.bulk_ingest --symbols AAPL,MSFT,KO,JNJ
```

> On macOS / Linux use `python` instead of `py`.

The first run will also download the SEC ticker→CIK map (~1 MB, cached on disk and refreshed weekly).

### 4. Build the industry catalog (Phase 3, optional but recommended)

To browse and screen by industry, first light-ingest a broad universe of company
profiles. This is fast (profile-only, batched) and populates the industry dropdowns.

```bash
cd backend

# Light-ingest profiles for the US-listed universe (~3000 tickers, ~20-30 min).
# Also available from the UI via the "Discover Universe" button on the Screener.
py -m ingestion.bulk_ingest --discover-universe

# Test on a small subset first (recommended)
py -m ingestion.bulk_ingest --discover-universe --sample 200
```

Then deep-ingest an industry to get full financials, scores, IV trends, and model
accuracy for its companies:

```bash
# Deep-ingest every company in an industry (auto-computes model accuracy)
py -m ingestion.bulk_ingest --industry "Banks - Diversified"

# Or just the top N by market cap
py -m ingestion.bulk_ingest --industry "Semiconductors" --limit 100

# Recompute model accuracy for an industry without re-ingesting (no API calls)
py -m ingestion.bulk_ingest --industry "Banks - Diversified" --compute-accuracy
```

Industry names come from yfinance and use the normalized `"Group - Subgroup"`
form (e.g. `"Banks - Regional"`, `"Drug Manufacturers - General"`). The
Industries tab in the UI does all of this without the command line.

## Running

Start both servers in separate terminals:

**Terminal 1 — Backend:**
```bash
cd backend
py app.py
```
Flask runs on http://localhost:5000

**Terminal 2 — Frontend:**
```bash
cd frontend
npm run dev
```
Vite runs on http://localhost:5173

Open http://localhost:5173 in your browser. The app has four tabs — **Screener**, **Industries**, **Analysis**, and **Backtest**. The screener works without an API key. The header shows "DB-only" mode; enter an FMP key only if you want the FMP fallback for tickers not in your local database.

The **Industries** tab is the fastest way to build real peer groups: pick a sub-industry, click **Deep Ingest All**, and once it finishes you get the full screener table for that industry plus its valuation-model accuracy rankings. Open any company in **Analysis** to see its intrinsic-value trend chart and its industry-weighted intrinsic value.

The **Backtest** tab has two modes. *Single Company* simulates the Graham strategy on one ticker. *Strategy (All Companies)* runs the cross-company backtest across your whole database — it re-scores every company for each historical year (using only data available at the time), buys quality names at a margin of safety, sells at a premium to intrinsic value, and charts the result against the S&P 500. The **Run Parameter Sweep** button tries every margin-of-safety × sell-premium combination and shows a heatmap of annualized returns. A full run re-scores thousands of companies per year, so expect 30–60 seconds (and several minutes for a full sweep).

## Maintaining the Database

```bash
cd backend

# Add a single ticker on demand (or let the UI's "Add Tickers" form do it)
py -m ingestion.bulk_ingest --symbols NVDA

# Daily price refresh (~5 min for 500 companies, no EDGAR re-fetch)
py -m ingestion.bulk_ingest --refresh-prices

# Recompute Graham/Fisher/valuation scores from existing DB data
# (no API calls — useful after editing the analysis modules). Also (re)computes
# IV trends and data-completeness values for the screener.
py -m ingestion.bulk_ingest --refresh-scores
```

EDGAR financial data only needs refreshing quarterly when 10-Ks are filed. Bulk ingest skips companies whose data is fresh (< 90 days old) by default; pass `--no-skip-existing` to force a full re-ingest.

## Storage

Roughly:
- 25 starter tickers, 16 years of daily prices: ~25 MB
- S&P 500, 16 years: ~350 MB
- 5,000 companies, 10+ years: ~700 MB

The bulk of the size is daily prices. Companies, financials, and scores together are < 50 MB even at 5,000-company scale.

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET    | `/api/health` | Liveness check |
| GET    | `/api/db/stats` | Counts and freshness of the local DB |
| GET    | `/api/sectors` | Distinct sectors present in the DB (for the screener dropdown) |
| GET    | `/api/search?query=...` | Search local DB by symbol/name; FMP fallback if `apikey` provided |
| GET    | `/api/screen?...` | Pure-SQL screener with filters: `sector`, `industry`, `capMin`, `capMax`, `grahamGrade`, `fisherGrade`, `minGrahamScore`, `signal`, `minDiscount`, `ivTrend`, `minCompleteness` (applies to both Graham & Fisher), `sortBy` (incl. `ivGrowth5yr`/`ivGrowth10yr`/`ivStability`), `sortDir`, `limit` |
| GET    | `/api/screen/export?...` | Same filters, returns CSV download |
| GET    | `/api/analyze/<sym>` | Run Graham + Fisher + valuation, plus `ivTrends` (historical IV vs price), industry-weighted valuation (`modelAccuracy`), and data-completeness metadata (`dataAvailable`, `dataCompleteness`, `adjustedPctScore`) on each engine. Auto-deep-ingests the ticker if it's missing or only light-ingested. Pass `?refresh=1` to force re-ingest. Pass `?source=fmp` (with `apikey`) for FMP path |
| GET    | `/api/backtest/<sym>?years=N&mos=0.35&sellPremium=0.20` | Single-company Graham backtest from local price history |
| POST   | `/api/backtest/strategy` | Cross-company strategy backtest. Body (all optional): `marginOfSafety`, `sellPremium`, `startYear`, `endYear`, `maxPositions`, `minCompleteness`, `startingCapital`. Returns summary, year-by-year data, trade log, and SPY benchmark series |
| POST   | `/api/backtest/strategy/sweep` | Runs the strategy backtest for every `mosValues[]` × `sellValues[]` combination; returns a summary per combo |
| POST   | `/api/ingest` | Body: `{"symbols":[...]}` or `{"universe":"starter\|sp500"}`. Optional `"skipExisting":true` |
| GET    | `/api/industries?sector=...&min_count=5` | Distinct industries with company counts (optionally filtered by sector) |
| GET    | `/api/industries/<industry>/companies?limit=N&sort_by=market_cap\|name` | Companies in an industry |
| GET    | `/api/industries/<industry>/status` | Ingestion status: light vs deep vs scored counts |
| GET    | `/api/industries/<industry>/accuracy` | Per-model prediction-error rankings and recommended weights (computed on demand if not cached) |
| POST   | `/api/ingest/discover` | Light-ingest the US-listed universe. Optional body `{"sample":N}` to limit for testing |
| POST   | `/api/ingest/industry` | Deep-ingest an industry. Body: `{"industry":"...", "limit":N}` |

## FMP API Key (optional)

The legacy FMP-based flow still works as a fallback. The free tier allows 250 requests/day; a full analysis uses 6 calls and a backtest uses 4. With Phase 2 you typically don't need a key at all — the database covers everything you've ingested, and you can ingest any US public company without one.

If you do want a key:
1. Go to https://financialmodelingprep.com/developer
2. Create a free account
3. Paste the key into the optional field in the app header

## Disclaimer

This tool is for educational and research purposes only. It is not financial advice. Always do your own research and consult a qualified financial advisor before making investment decisions.
