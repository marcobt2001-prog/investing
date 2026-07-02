# Value Investor Intelligence System — Phase 3 Spec
# Industry Deep-Dive, Intrinsic Value Trends, Model Accuracy

## What This Phase Adds

Phase 2 gave us a local data pipeline with ~25 companies. Phase 3 makes the system
genuinely useful for real investment research by adding three capabilities:

1. **Industry-Focused Bulk Ingestion** — Pick a sub-industry, discover every public
   company in it, and ingest them all. This gives you real peer groups of 50-500+
   companies to screen and compare.

2. **Intrinsic Value Trend Tracking** — Compute historical intrinsic values year by year
   for each company, so you can see whether a company's value is growing, flat, or declining.
   This directly addresses the problem of "intrinsic value drops the year after you buy."

3. **Valuation Model Accuracy by Industry** — For each industry, which valuation model
   was most predictive of future stock prices? Weight models accordingly. This replaces the
   regression idea with something simpler and more robust.

---

## Architecture Changes

```
backend/
├── database/
│   ├── db.py               # Updated: 2 new tables
│   └── models.py            # Updated: new helpers for new tables
├── ingestion/
│   ├── bulk_ingest.py        # Updated: industry discovery + light ingest
│   ├── industry_discovery.py # NEW: find all companies in an industry
│   └── ...
├── analysis/
│   ├── graham.py             # Unchanged
│   ├── fisher.py             # Unchanged
│   ├── valuation.py          # Unchanged
│   ├── backtest.py           # Unchanged
│   ├── iv_trends.py          # NEW: historical intrinsic value computation
│   └── model_accuracy.py     # NEW: per-industry model accuracy scoring
├── app.py                    # Updated: new routes
frontend/
└── src/
    └── components/
        ├── Screener.jsx      # Updated: industry picker + discovery UI
        ├── Analysis.jsx      # Updated: IV trend chart + model accuracy display
        └── IndustryView.jsx  # NEW: industry-level analysis page
```

---

## Part 1: Industry-Focused Bulk Ingestion

### The Problem

Right now you have ~25 companies. You can't meaningfully screen or compare within
an industry. You also can't run any statistical analysis with such a small sample.

### The Solution: Two-Phase Ingestion

**Light Ingest (fast):** Fetch just the company profile (name, sector, industry,
market cap, price) for a large universe. This is one yfinance call per ticker,
no EDGAR needed. Purpose: build a catalog of companies with their industry
classifications so users can browse and select industries.

**Deep Ingest (slower):** For a selected industry or set of tickers, fetch full
EDGAR financials + price history + compute scores. This is the full pipeline
from Phase 2.

### New File: `ingestion/industry_discovery.py`

```python
def get_all_tickers() -> list[dict]:
    """
    Get a comprehensive list of US-listed tickers from the SEC company
    tickers file (already cached from Phase 2).

    Returns list of {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc"}.

    Filter to only include companies listed on NYSE, NASDAQ, AMEX.
    The SEC file includes many OTC, foreign, and defunct companies — filter those out.
    """

def light_ingest_batch(symbols: list[str], batch_size: int = 50) -> int:
    """
    Fast profile-only ingestion for a large number of tickers.

    For each ticker, fetch just the yfinance profile (name, sector, industry,
    market cap, price, exchange) and upsert into the companies table.
    No EDGAR call, no price history, no scoring.

    Use yf.Tickers("AAPL MSFT KO ...") for batch fetching — much faster
    than one-by-one. Process in batches of 50 to avoid timeouts.

    Skip tickers that already have a profile updated within the last 30 days.

    Returns count of successfully ingested companies.
    """

def get_available_industries() -> list[dict]:
    """
    Query the local companies table and return a list of distinct industries
    with company counts, sorted by count descending.

    Returns: [
        {"industry": "Banks—Regional", "sector": "Financial Services", "count": 142},
        {"industry": "Insurance—Property & Casualty", "sector": "Financial Services", "count": 87},
        ...
    ]

    Only include industries where count >= 5 (skip industries with too few companies
    to be useful).
    """

def get_companies_in_industry(industry: str) -> list[dict]:
    """
    Return all companies in the local DB matching the given industry name.
    Returns basic company info (symbol, name, market_cap, sector, industry).
    """

def deep_ingest_industry(industry: str, limit: int = None) -> dict:
    """
    Full ingestion (EDGAR + prices + scores) for all companies in an industry.

    1. Get all tickers in the given industry from the companies table
    2. If limit is specified, take the top N by market cap
    3. Run full ingest_company() for each (skipping those already fully ingested < 90 days)
    4. Return summary: {"total": 142, "ingested": 130, "skipped": 8, "failed": 4, "errors": [...]}
    """
```

### Building the Universe Catalog

The first time a user wants to browse industries, they need a catalog.
Add a CLI command and a Flask route to build it:

```bash
# CLI: light-ingest the top ~3000 US companies by market cap
py -m ingestion.bulk_ingest --discover-universe

# This will:
# 1. Load SEC tickers file
# 2. Filter to NYSE/NASDAQ/AMEX
# 3. Batch-fetch yfinance profiles (just sector/industry/market cap)
# 4. Store in companies table
# 5. Takes ~20-30 minutes for 3000 tickers
```

### Updated Database Helpers in `models.py`

```python
def get_industries(min_count: int = 5) -> list[dict]:
    """Return distinct industries with company counts."""

def get_companies_by_industry(industry: str, limit: int = None) -> list[dict]:
    """Return all companies in a given industry, ordered by market_cap DESC."""

def get_sectors() -> list[dict]:
    """Return distinct sectors with industry counts and company counts."""

def get_ingestion_status(industry: str) -> dict:
    """
    For a given industry, return how many companies have:
    - profile only (light ingested)
    - full financials (deep ingested)
    - scores computed
    """
```

### New Flask Routes

```
GET /api/industries
    Returns list of industries with counts.
    Query params: sector (optional filter), min_count (default 5)

GET /api/industries/<industry>/companies
    Returns companies in an industry.
    Query params: limit, sort_by (market_cap, name)

GET /api/industries/<industry>/status
    Returns ingestion status for an industry.

POST /api/ingest/discover
    Trigger light ingestion of the full universe (~3000 tickers).
    Returns immediately with a job status. Runs in background.
    (For simplicity, can run synchronously with progress — the frontend
    should show a progress indicator.)

POST /api/ingest/industry
    Body: {"industry": "Banks—Regional", "limit": 100}
    Trigger deep ingestion for all companies in an industry.
```

### Frontend: Updated Screener + New Industry View

**Screener updates:**
- Add an "Industry" dropdown alongside the existing "Sector" dropdown.
  When a sector is selected, populate the industry dropdown with
  sub-industries in that sector (from `/api/industries?sector=X`).
- Add a "Discover Universe" button in the Data Status panel that
  triggers the light ingest of ~3000 companies.

**New tab or section: Industry View**
- Pick an industry from a dropdown
- See all companies in it, their ingestion status, and a "Deep Ingest All" button
- Once ingested, see the full screener table filtered to just that industry
- Show industry-level statistics: average P/E, average Graham score, best/worst companies

---

## Part 2: Intrinsic Value Trend Tracking

### The Problem

Currently, intrinsic value is computed only for the most recent year. You can't see
whether a company's intrinsic value is growing or declining. This leads to false
positives: a company looks undervalued because its intrinsic value is high relative
to price, but next year intrinsic value drops and the "discount" evaporates.

### New Database Table: `historical_valuations`

```sql
CREATE TABLE IF NOT EXISTS historical_valuations (
    symbol TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    model TEXT NOT NULL,        -- "graham", "dcf", "book_value", "epv", "ncav"
    intrinsic_value REAL,       -- Per-share intrinsic value estimate
    inputs TEXT,                -- JSON blob of inputs used (EPS, growth rate, etc.)
    PRIMARY KEY (symbol, fiscal_year, model)
);
```

Storage is minimal — 5 models × 10 years × 5000 companies = 250K rows, ~15 MB.

### New Analysis Module: `analysis/iv_trends.py`

```python
def compute_historical_valuations(symbol: str, financials: list[dict],
                                   profile: dict) -> list[dict]:
    """
    For each fiscal year in the financials data, compute intrinsic value
    using all 5 valuation models AS IF that year were the current year.

    This means:
    - Graham formula uses that year's EPS and the growth rate UP TO that year
    - DCF uses that year's FCF and historical FCF growth up to that year
    - Book value uses that year's equity
    - EPV uses the 5-year average earnings ENDING in that year
    - NCAV uses that year's current assets and total liabilities

    For price comparison, use the average stock price during that fiscal year
    (from the daily_prices table).

    Returns: [
        {
            "fiscal_year": 2020,
            "avg_price": 45.23,
            "models": {
                "graham": {"intrinsic_value": 52.10, "inputs": {...}},
                "dcf": {"intrinsic_value": 61.40, "inputs": {...}},
                "book_value": {"intrinsic_value": 28.50, "inputs": {...}},
                "epv": {"intrinsic_value": 48.90, "inputs": {...}},
                "ncav": {"intrinsic_value": -12.30, "inputs": {...}},
            },
            "composite": 47.73,  # Average of positive models
        },
        ...
    ]
    """

def compute_iv_growth_rate(historical_valuations: list[dict]) -> dict:
    """
    Compute the compound annual growth rate of composite intrinsic value.

    Returns: {
        "cagr_5yr": 0.08,    # 8% annual IV growth over last 5 years
        "cagr_10yr": 0.06,
        "trend": "growing",  # "growing", "stable", "declining"
        "stability": 0.85,   # R-squared of log-linear fit (how steady is the growth?)
        "recent_direction": "up",  # Did IV go up or down in the most recent year?
    }
    """
```

### Integration Points

**In `bulk_ingest.py` → `compute_and_store_scores()`:**
After computing current scores, also call `compute_historical_valuations()` and
store results in the `historical_valuations` table.

**In `app.py` → `/api/analyze/<symbol>` response:**
Add an `"ivTrends"` field to the analysis response:
```json
{
    "symbol": "KO",
    "graham": {...},
    "fisher": {...},
    "valuation": {...},
    "ivTrends": {
        "history": [
            {"fiscal_year": 2015, "composite": 38.5, "avg_price": 41.2},
            {"fiscal_year": 2016, "composite": 40.1, "avg_price": 42.8},
            ...
        ],
        "growthRate": {
            "cagr_5yr": 0.06,
            "cagr_10yr": 0.05,
            "trend": "growing",
            "stability": 0.82
        },
        "modelHistory": {
            "graham": [38.2, 39.5, 41.0, ...],
            "dcf": [45.1, 47.2, 50.3, ...],
            ...
        }
    }
}
```

**In the scores table:**
Add new columns (or add to the upsert):
```sql
ALTER TABLE scores ADD COLUMN iv_cagr_5yr REAL;
ALTER TABLE scores ADD COLUMN iv_cagr_10yr REAL;
ALTER TABLE scores ADD COLUMN iv_trend TEXT;       -- "growing" / "stable" / "declining"
ALTER TABLE scores ADD COLUMN iv_stability REAL;   -- R-squared
```

These are now available as screener filters. Users can filter for
"only companies with growing intrinsic value" or sort by IV growth rate.

**In the Screener:**
Add new filter/sort options:
- IV Trend dropdown: All, Growing, Stable, Declining
- Sort by: IV Growth (5yr), IV Growth (10yr), IV Stability

**In the Analysis UI:**
Add a chart showing intrinsic value vs stock price over time.
Each valuation model shown as a separate line, plus the composite.
Stock price shown as another line. The visual makes it immediately
obvious whether IV is growing and whether the stock tends to trade
above or below intrinsic value.

Use a simple HTML canvas or a charting approach that doesn't require
new dependencies (the frontend already has React). A simple SVG-based
line chart built in React is fine, or use recharts if you want
something polished (it's already available as a library).

---

## Part 3: Valuation Model Accuracy by Industry

### The Problem

Not all valuation models work equally well for all industries. Book value is
meaningful for banks but useless for software companies. DCF works well for
stable cash flow businesses but poorly for cyclicals. Using a naive average
of all models produces a muddled signal.

### The Approach

For each company in the database with sufficient history:
1. Look at the intrinsic value each model estimated 3 years ago.
2. Look at the actual average stock price in the current year.
3. Compute the prediction error for each model: `abs(predicted - actual) / actual`.
4. Aggregate prediction errors by industry.
5. The model with the lowest average error for an industry is the most accurate
   for that industry.

This is NOT a regression. It's a simple accuracy ranking.

### New Analysis Module: `analysis/model_accuracy.py`

```python
def compute_model_accuracy(symbol: str, historical_valuations: list[dict],
                            daily_prices: list[dict]) -> dict:
    """
    For each model, compute the prediction error at 1-year, 3-year, and 5-year horizons.

    For example, if in 2019 the Graham model estimated intrinsic value at $50,
    and the actual average price in 2022 was $45, the 3-year prediction error
    for Graham is |50 - 45| / 45 = 11.1%.

    Returns: {
        "graham": {"error_1yr": 0.15, "error_3yr": 0.11, "error_5yr": 0.08},
        "dcf": {"error_1yr": 0.22, "error_3yr": 0.18, "error_5yr": 0.14},
        "book_value": {"error_1yr": 0.45, "error_3yr": 0.40, "error_5yr": 0.38},
        "epv": {"error_1yr": 0.12, "error_3yr": 0.09, "error_5yr": 0.07},
        "ncav": {"error_1yr": null, "error_3yr": null, "error_5yr": null},  # Usually negative/invalid
    }

    Only compute errors for years where we have both the prediction and the
    actual future price. Null out models where there aren't enough data points (< 3).
    """

def compute_industry_model_accuracy(industry: str) -> dict:
    """
    Aggregate model accuracy across all companies in an industry.

    Returns: {
        "industry": "Banks—Regional",
        "company_count": 87,
        "best_model_3yr": "book_value",
        "model_rankings": {
            "book_value": {"avg_error_3yr": 0.18, "rank": 1, "weight": 0.30},
            "epv": {"avg_error_3yr": 0.22, "rank": 2, "weight": 0.27},
            "graham": {"avg_error_3yr": 0.25, "rank": 3, "weight": 0.23},
            "dcf": {"avg_error_3yr": 0.35, "rank": 4, "weight": 0.15},
            "ncav": {"avg_error_3yr": 0.60, "rank": 5, "weight": 0.05},
        },
        "recommended_weights": {
            "book_value": 0.30,
            "epv": 0.27,
            "graham": 0.23,
            "dcf": 0.15,
            "ncav": 0.05,
        }
    }

    Weight calculation: inverse of error, normalized to sum to 1.
    Models with null/insufficient data get weight 0.
    """

def compute_weighted_intrinsic_value(symbol: str, valuations: dict,
                                       industry_weights: dict) -> float:
    """
    Compute a weighted intrinsic value using industry-specific model weights
    instead of a naive average.

    valuations: the output of compute_valuations() — contains per-model intrinsic values
    industry_weights: the recommended_weights from compute_industry_model_accuracy()

    Returns: weighted intrinsic value per share
    """
```

### New Database Table: `model_accuracy`

```sql
CREATE TABLE IF NOT EXISTS model_accuracy (
    industry TEXT NOT NULL,
    model TEXT NOT NULL,           -- "graham", "dcf", "book_value", "epv", "ncav"
    avg_error_1yr REAL,
    avg_error_3yr REAL,
    avg_error_5yr REAL,
    sample_size INTEGER,          -- How many company-years went into this average
    rank_3yr INTEGER,             -- 1 = best model for this industry
    recommended_weight REAL,      -- 0.0 to 1.0
    last_computed TEXT,            -- ISO datetime
    PRIMARY KEY (industry, model)
);
```

### Integration Points

**In `bulk_ingest.py`:**
After deep-ingesting an industry, automatically compute model accuracy for that industry.
Add a CLI flag:
```bash
py -m ingestion.bulk_ingest --compute-accuracy --industry "Banks—Regional"
```

**In `app.py`:**

New route:
```
GET /api/industries/<industry>/accuracy
    Returns model accuracy rankings for an industry.
```

Updated `/api/analyze/<symbol>` response:
Add a `"modelAccuracy"` field showing the industry-specific weights and
a `"weightedIntrinsicValue"` that uses those weights instead of naive average.

```json
{
    "valuation": {
        "models": {...},
        "compositeValue": 45.23,
        "weightedValue": 48.91,
        "industryWeights": {
            "book_value": 0.30,
            "epv": 0.27,
            ...
        },
        "signal": "BUY",
        "weightedSignal": "STRONG BUY"
    }
}
```

Show BOTH the naive composite and the industry-weighted value so the user
can see the difference and understand why.

**In the Analysis UI:**
- Show both "Composite Intrinsic Value" and "Industry-Weighted Intrinsic Value"
- Show which model is most/least accurate for this company's industry
- Visual indicator (bar chart or ranked list) of model weights

**In the Industry View:**
- Show model accuracy rankings for the selected industry
- Show which model to trust most and least

---

## Updated Screener Filters

After Phase 3, the screener supports these filters:

| Filter | Values | Source |
|--------|--------|--------|
| Sector | Dropdown | companies table |
| Industry | Dropdown (filtered by sector) | companies table |
| Market Cap | Range dropdown | companies table |
| Graham Grade | A / B / C / D | scores table |
| Fisher Grade | A / B / C / D | scores table |
| Signal | STRONG BUY / BUY / HOLD / etc. | scores table |
| Min Discount | Percentage slider | scores table |
| IV Trend | Growing / Stable / Declining | scores table (NEW) |
| Sort By | Any of: graham_pct, fisher_pct, discount, iv_cagr_5yr, market_cap | |
| Direction | Asc / Desc | |

---

## Step-by-Step Build Order

### Step 1: Database schema updates

1. Add `historical_valuations` table to `db.py` schema.
2. Add `model_accuracy` table to `db.py` schema.
3. Add new columns to `scores` table: `iv_cagr_5yr`, `iv_cagr_10yr`, `iv_trend`, `iv_stability`.
4. Add helper functions to `models.py`:
   - `upsert_historical_valuation(symbol, fiscal_year, model, intrinsic_value, inputs)`
   - `get_historical_valuations(symbol)` → list
   - `upsert_model_accuracy(industry, model, **fields)`
   - `get_model_accuracy(industry)` → list of model accuracy rows
   - `get_industries(min_count)` → list of industries with counts
   - `get_companies_by_industry(industry, limit)` → list
   - `get_ingestion_status(industry)` → dict with counts
5. Update `screen_companies()` to support new filters: `iv_trend`, sort by `iv_cagr_5yr`.
6. Test: create tables, insert dummy data, query it back.

### Step 2: Industry discovery (`ingestion/industry_discovery.py`)

1. Implement `get_all_tickers()` — load from SEC tickers file, filter to major exchanges.
2. Implement `light_ingest_batch()` — batch yfinance profile fetch, upsert to companies.
3. Implement `get_available_industries()` — query DB for distinct industries with counts.
4. Implement `get_companies_in_industry()` and `deep_ingest_industry()`.
5. Add CLI commands to `bulk_ingest.py`:
   - `--discover-universe` — light ingest of top ~3000 US tickers
   - `--industry "Banks—Regional"` — deep ingest all companies in an industry
   - `--industry "Banks—Regional" --limit 100` — deep ingest top 100 by market cap
6. Test: run `--discover-universe` on a small subset (100 tickers), verify industries populated.
   Then `--industry` on one small industry, verify full financials ingested.

### Step 3: Intrinsic value trends (`analysis/iv_trends.py`)

1. Implement `compute_historical_valuations()` — runs all 5 valuation models for each
   historical year. This reuses the existing `valuation.py` functions but feeds them
   historical data. The tricky part: for each year Y, you need to construct the inputs
   as if you were standing in year Y:
   - Only use financials from year Y and earlier
   - Use the average stock price during year Y as the "current price"
   - Use EPS growth rate computed only from data available in year Y
2. Implement `compute_iv_growth_rate()` — CAGR + trend + stability.
3. Integrate into `compute_and_store_scores()` in `bulk_ingest.py`:
   - After computing current valuations, also compute historical valuations
   - Store in `historical_valuations` table
   - Compute IV growth metrics and store in `scores` table
4. Test: compute historical valuations for AAPL and KO. Verify that IV values
   for 2015 are different from 2020 and that the growth rate makes sense.

### Step 4: Model accuracy (`analysis/model_accuracy.py`)

1. Implement `compute_model_accuracy()` for a single company.
2. Implement `compute_industry_model_accuracy()` — aggregate across an industry.
3. Implement `compute_weighted_intrinsic_value()`.
4. Add CLI command: `--compute-accuracy --industry "X"`.
5. Auto-trigger after `--industry` deep ingestion completes.
6. Test: compute accuracy for an industry with at least 10 companies.
   Verify that model rankings make intuitive sense (e.g. book value should
   rank higher for banks than for tech companies).

### Step 5: Flask route updates

1. Add industry routes: `/api/industries`, `/api/industries/<industry>/companies`,
   `/api/industries/<industry>/status`, `/api/industries/<industry>/accuracy`.
2. Add `POST /api/ingest/discover` — trigger light universe discovery.
3. Add `POST /api/ingest/industry` — trigger deep industry ingestion.
4. Update `/api/analyze/<symbol>` to include `ivTrends` and `modelAccuracy` in response.
5. Update `/api/screen` to support `iv_trend` filter and `iv_cagr_5yr` sort.
6. Test all routes with curl.

### Step 6: Frontend updates

1. **Screener.jsx:** Add Industry dropdown (populated from `/api/industries`),
   IV Trend filter, IV Growth sort option. Add "Discover Universe" button
   in Data Status panel.
2. **Analysis.jsx:** Add IV Trends section with a line chart (intrinsic value vs price
   over time, one line per model + composite + actual price). Add Model Accuracy
   section showing industry-specific weights. Show both composite and weighted
   intrinsic values.
3. **New: IndustryView.jsx** (or a section within Screener):
   - Industry picker dropdown
   - Shows company count, ingestion status, "Deep Ingest" button
   - After ingestion: model accuracy rankings, top companies by score
4. **App.jsx:** Add "Industries" as a new tab, render IndustryView component.

### Step 7: Test end-to-end and update README

1. Run `--discover-universe` with a small set to populate industries.
2. Pick one industry, deep ingest it.
3. Verify screener shows IV trends and new filters work.
4. Verify Analysis page shows IV trend chart and model accuracy.
5. Verify Industry View shows accuracy rankings.
6. Update README with new features and CLI commands.

---

## Important Notes

- **Don't rewrite existing analysis engines.** The Phase 2 analysis modules work.
  Build new modules alongside them and feed them the same data.

- **Historical valuation computation is CPU-intensive but not API-intensive.**
  It's re-running the valuation models on data already in the DB. No new API calls.
  For 100 companies × 10 years × 5 models = 5,000 valuations. Should take < 30 seconds.

- **Industry names from yfinance can be inconsistent.** "Banks—Regional" vs
  "Regional Banks" vs "Banks - Regional". Normalize industry names on ingestion:
  strip extra whitespace, standardize dashes, lowercase for comparison but store
  the original casing for display.

- **Model accuracy requires at least 3 years of history to be meaningful.**
  For a 3-year prediction error, you need valuations from 3+ years ago AND
  price data for the current year. Skip companies with insufficient history.

- **The IV trend chart is the single most important UI addition in this phase.**
  A user should be able to look at one chart and immediately see: "this company's
  intrinsic value has been growing steadily at 8% per year and the stock is currently
  trading 30% below" vs "this company's intrinsic value has been flat or declining."
  That visual is worth more than any single number.
