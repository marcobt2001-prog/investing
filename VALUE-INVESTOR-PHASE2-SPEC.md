# Value Investor Intelligence System — Phase 2 Spec
# Local Data Pipeline: SEC EDGAR + yfinance + SQLite

## Why This Phase Exists

The current system relies entirely on the FMP free tier (250 requests/day).
The screener hardcodes ~220 symbols and makes 1 API call per symbol just to list them.
A full analysis uses 6 calls. Statement history is capped at 5 years. This makes the
tool impractical — you run out of API calls after analyzing a handful of stocks.

This phase replaces FMP as the primary data source with:
- **SEC EDGAR** (free, no API key, covers every US public company) for financial statements
- **yfinance** (free, unofficial Yahoo Finance wrapper) for prices, profiles, and market data
- **SQLite** local database for persistent storage and fast querying

FMP remains available as a fallback/supplement but is no longer required.

---

## Architecture Overview

```
value-investor/
├── backend/
│   ├── app.py                    # Flask server (mostly unchanged routes)
│   ├── database/
│   │   ├── __init__.py
│   │   ├── db.py                 # SQLite connection manager + schema init
│   │   ├── models.py             # Table definitions & helper queries
│   │   └── value_investor.db     # SQLite database file (created at runtime)
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── edgar.py              # SEC EDGAR XBRL data fetcher + parser
│   │   ├── yfinance_fetcher.py   # yfinance wrapper for prices + profiles
│   │   ├── bulk_ingest.py        # Orchestrator: bulk load companies into DB
│   │   └── field_mapping.py      # XBRL tag → normalized field name mapping
│   ├── analysis/                 # (existing — unchanged)
│   │   ├── graham.py
│   │   ├── fisher.py
│   │   ├── valuation.py
│   │   └── backtest.py
│   └── requirements.txt          # Add: yfinance, sqlite3 is stdlib
├── frontend/                     # (existing — updated Screener component)
└── README.md
```

---

## Database Schema (SQLite)

### Table: companies
Core company info. One row per ticker.

```sql
CREATE TABLE IF NOT EXISTS companies (
    symbol TEXT PRIMARY KEY,
    name TEXT,
    sector TEXT,
    industry TEXT,
    exchange TEXT,
    market_cap REAL,
    price REAL,
    shares_outstanding REAL,
    beta REAL,
    dividend_yield REAL,
    description TEXT,
    cik TEXT,                -- SEC Central Index Key (10-digit, zero-padded)
    last_profile_update TEXT -- ISO date of last yfinance profile fetch
);
```

### Table: financials
Annual financial statement data. One row per company per year.
This is the key table — it flattens income statement, balance sheet,
and cash flow into a single row per company-year for easy querying.

```sql
CREATE TABLE IF NOT EXISTS financials (
    symbol TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    fiscal_date TEXT,           -- e.g. "2024-12-31"
    source TEXT,                -- "edgar" or "fmp" (track where data came from)

    -- Income Statement
    revenue REAL,
    cost_of_revenue REAL,
    gross_profit REAL,
    operating_income REAL,
    net_income REAL,
    eps REAL,
    eps_diluted REAL,
    research_and_development REAL,
    sga_expense REAL,            -- Selling, General & Administrative
    weighted_avg_shares REAL,
    weighted_avg_shares_diluted REAL,

    -- Balance Sheet
    total_assets REAL,
    total_current_assets REAL,
    total_liabilities REAL,
    total_current_liabilities REAL,
    total_debt REAL,
    total_stockholders_equity REAL,
    retained_earnings REAL,
    cash_and_equivalents REAL,

    -- Cash Flow Statement
    operating_cash_flow REAL,
    capital_expenditure REAL,
    free_cash_flow REAL,
    dividends_paid REAL,         -- Negative when dividends are paid out

    -- Computed at ingestion time
    current_ratio REAL,
    debt_to_equity REAL,
    gross_margin REAL,
    operating_margin REAL,
    net_margin REAL,
    roe REAL,                    -- Return on Equity
    roa REAL,                    -- Return on Assets
    fcf_margin REAL,

    -- Metadata
    fetched_at TEXT,             -- ISO datetime when this row was fetched

    PRIMARY KEY (symbol, fiscal_year)
);
```

### Table: daily_prices
Historical daily prices for backtesting. One row per ticker per date.

```sql
CREATE TABLE IF NOT EXISTS daily_prices (
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,         -- "YYYY-MM-DD"
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    adj_close REAL,
    volume INTEGER,
    PRIMARY KEY (symbol, date)
);
```

### Table: scores
Pre-computed Graham and Fisher scores. Updated when financials are refreshed.
This is what makes the screener fast — no re-computation needed at query time.

```sql
CREATE TABLE IF NOT EXISTS scores (
    symbol TEXT PRIMARY KEY,
    -- Graham
    graham_total REAL,
    graham_max REAL,
    graham_pct REAL,
    graham_grade TEXT,          -- A/B/C/D
    graham_details TEXT,        -- JSON blob of individual criteria scores

    -- Fisher
    fisher_total REAL,
    fisher_max REAL,
    fisher_pct REAL,
    fisher_grade TEXT,
    fisher_details TEXT,        -- JSON blob

    -- Valuation
    intrinsic_value_graham REAL,
    intrinsic_value_dcf REAL,
    intrinsic_value_book REAL,
    intrinsic_value_epv REAL,
    intrinsic_value_ncav REAL,
    intrinsic_value_composite REAL,
    discount_to_intrinsic REAL, -- (intrinsic - price) / intrinsic
    signal TEXT,                -- STRONG BUY / BUY / HOLD / OVERVALUED / STRONG SELL

    -- Metadata
    last_computed TEXT           -- ISO datetime
);
```

### Storage estimate
- 5,000 companies × ~500 bytes = ~2.5 MB for companies table
- 5,000 companies × 10 years × ~800 bytes = ~40 MB for financials
- 5,000 companies × 2,500 trading days × ~50 bytes = ~625 MB for daily_prices
- 5,000 companies × ~2 KB = ~10 MB for scores

**Total: ~700 MB for 5,000 companies with 10 years of data.**
If storage is a concern, start with a smaller universe (e.g. S&P 500 + Russell 2000 small caps = ~2,500 stocks, ~350 MB).

Price data is the biggest table. Could optionally store only weekly or monthly prices to cut it by 80%, though daily is better for backtesting accuracy.

---

## Step-by-Step Build Order

### Step 1: Database setup (`database/db.py`, `database/models.py`)

1. Create `db.py` with a `get_db()` function that returns a SQLite connection.
   - DB file lives at `backend/database/value_investor.db`
   - Enable WAL mode for better concurrent read performance
   - Create all tables on first run using the schema above
2. Create `models.py` with helper functions:
   - `upsert_company(symbol, **fields)` — insert or update a company row
   - `upsert_financials(symbol, fiscal_year, **fields)` — insert or update financials
   - `upsert_daily_prices(symbol, rows)` — bulk insert price data
   - `upsert_scores(symbol, **fields)` — insert or update pre-computed scores
   - `get_company(symbol)` → dict or None
   - `get_financials(symbol, limit=12)` → list of dicts, most recent first
   - `get_daily_prices(symbol, start_date=None)` → list of dicts
   - `get_scores(symbol)` → dict or None
   - `search_companies(query)` → list of matching companies (name or symbol LIKE)
   - `screen_companies(sector, cap_min, cap_max, graham_grade, min_graham_score, ...)` → filtered list

3. Test: create DB, insert a dummy row, query it back, verify schema.

### Step 2: SEC EDGAR fetcher (`ingestion/edgar.py`)

The SEC EDGAR XBRL API gives us every financial fact a company has ever filed.

**Key endpoint:**
```
https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json
```
Returns ALL facts ever reported by that company, organized by taxonomy and tag.

**Required headers:**
```python
headers = {
    "User-Agent": "ValueInvestor your-email@example.com",  # SEC requires this
    "Accept": "application/json",
}
```
SEC requires a User-Agent with a name and contact email. They will block requests without it.

**Rate limiting:** SEC asks for max 10 requests per second. Implement a simple rate limiter.

**CIK lookup:** To go from ticker → CIK, use:
```
https://efts.sec.gov/LATEST/search-index?q=%22AAPL%22&dateRange=custom&startdt=2024-01-01&enddt=2024-12-31
```
Or use the bulk ticker-to-CIK mapping file:
```
https://www.sec.gov/files/company_tickers.json
```
This is a single JSON file mapping every ticker to its CIK. Download it once and cache it.

**XBRL tag mapping (`field_mapping.py`):**
The main challenge with EDGAR is that XBRL tags vary across companies. Create a mapping from
common XBRL tags to our normalized field names:

```python
XBRL_TO_FIELD = {
    # Revenue
    "Revenues": "revenue",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "RevenueFromContractWithCustomerIncludingAssessedTax": "revenue",
    "SalesRevenueNet": "revenue",
    "SalesRevenueGoodsNet": "revenue",

    # Cost of Revenue
    "CostOfRevenue": "cost_of_revenue",
    "CostOfGoodsAndServicesSold": "cost_of_revenue",
    "CostOfGoodsSold": "cost_of_revenue",

    # Net Income
    "NetIncomeLoss": "net_income",
    "ProfitLoss": "net_income",

    # Operating Income
    "OperatingIncomeLoss": "operating_income",

    # EPS
    "EarningsPerShareBasic": "eps",
    "EarningsPerShareDiluted": "eps_diluted",

    # Total Assets
    "Assets": "total_assets",

    # Current Assets
    "AssetsCurrent": "total_current_assets",

    # Total Liabilities
    "Liabilities": "total_liabilities",

    # Current Liabilities
    "LiabilitiesCurrent": "total_current_liabilities",

    # Stockholders Equity
    "StockholdersEquity": "total_stockholders_equity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": "total_stockholders_equity",

    # Total Debt
    "LongTermDebt": "total_debt",
    "LongTermDebtAndCapitalLeaseObligations": "total_debt",
    "DebtCurrent": "total_debt",  # Note: may need to sum current + long-term

    # Cash
    "CashAndCashEquivalentsAtCarryingValue": "cash_and_equivalents",

    # R&D
    "ResearchAndDevelopmentExpense": "research_and_development",

    # SGA
    "SellingGeneralAndAdministrativeExpense": "sga_expense",

    # Shares Outstanding
    "CommonStockSharesOutstanding": "weighted_avg_shares",
    "WeightedAverageNumberOfShareOutstandingBasicAndDiluted": "weighted_avg_shares",
    "WeightedAverageNumberOfDilutedSharesOutstanding": "weighted_avg_shares_diluted",

    # Cash Flow
    "NetCashProvidedByUsedInOperatingActivities": "operating_cash_flow",
    "PaymentsToAcquirePropertyPlantAndEquipment": "capital_expenditure",
    "PaymentsOfDividends": "dividends_paid",
    "PaymentsOfDividendsCommonStock": "dividends_paid",

    # Retained Earnings
    "RetainedEarningsAccumulatedDeficit": "retained_earnings",
}
```

**NOTE:** This mapping will NOT cover every company perfectly. Some companies use proprietary
XBRL extensions. The fetcher should do its best and log warnings for fields it can't map.
This is expected and okay — we'll improve coverage over time.

**Implementation:**
```python
def fetch_company_facts(cik: str) -> dict:
    """Fetch all XBRL facts for a company from SEC EDGAR."""
    # Returns raw JSON from SEC

def parse_annual_financials(facts: dict, ticker: str) -> list[dict]:
    """
    Parse raw EDGAR facts into a list of annual financial records.
    Each dict has our normalized field names and corresponds to one fiscal year.

    Key logic:
    - Filter for 10-K filings only (form = "10-K")
    - For each fact, take the value from the most recent filing for that fiscal year
      (companies sometimes restate numbers in later filings)
    - Group by fiscal year
    - Apply XBRL_TO_FIELD mapping
    - Compute derived fields: current_ratio, gross_margin, operating_margin, etc.
    """
```

The tricky parts:
- Some facts are reported quarterly only — need to filter for annual (10-K, period of ~365 days)
- A company might report `Revenues` in one year and `RevenueFromContractWithCustomerExcludingAssessedTax` in another
- Free Cash Flow is usually not reported directly — compute as `operating_cash_flow - abs(capital_expenditure)`
- Gross Profit is sometimes reported directly, sometimes needs to be computed as `revenue - cost_of_revenue`

Test: Fetch data for AAPL (CIK 0000320193), parse it, print 5 years of revenue + net income.

### Step 3: yfinance fetcher (`ingestion/yfinance_fetcher.py`)

yfinance fills in what EDGAR doesn't provide well: real-time prices, historical daily prices,
company profiles, sector/industry classification.

```python
import yfinance as yf

def fetch_profile(symbol: str) -> dict:
    """
    Fetch company profile: name, sector, industry, market cap, price,
    shares outstanding, beta, dividend yield, exchange, description.
    """
    ticker = yf.Ticker(symbol)
    info = ticker.info
    return {
        "symbol": symbol,
        "name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "market_cap": info.get("marketCap"),
        "price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "shares_outstanding": info.get("sharesOutstanding"),
        "beta": info.get("beta"),
        "dividend_yield": info.get("dividendYield"),
        "exchange": info.get("exchange"),
        "description": info.get("longBusinessSummary"),
    }

def fetch_daily_prices(symbol: str, start: str = "2010-01-01") -> list[dict]:
    """Fetch daily OHLCV price data."""
    ticker = yf.Ticker(symbol)
    df = ticker.history(start=start, auto_adjust=False)
    rows = []
    for date, row in df.iterrows():
        rows.append({
            "symbol": symbol,
            "date": date.strftime("%Y-%m-%d"),
            "open": row.get("Open"),
            "high": row.get("High"),
            "low": row.get("Low"),
            "close": row.get("Close"),
            "adj_close": row.get("Adj Close") or row.get("Close"),
            "volume": int(row.get("Volume", 0)),
        })
    return rows
```

yfinance can also provide financial statements, but EDGAR is more complete and authoritative.
Use yfinance financials only as a fallback when EDGAR data is missing for a company.

**Rate limiting:** yfinance doesn't have official limits but will throttle you if you
hammer it. Add a 0.5-second delay between requests. For bulk operations, batch tickers
using `yf.download(["AAPL", "MSFT", ...])` which is much faster than one-by-one.

Test: Fetch profile for KO, fetch 1 year of daily prices, print results.

### Step 4: Bulk ingestion orchestrator (`ingestion/bulk_ingest.py`)

This is the script that populates the database. It should be runnable from the
command line and support incremental updates.

```python
def get_sp500_tickers() -> list[str]:
    """Scrape or hardcode the current S&P 500 constituents."""
    # Can scrape from Wikipedia or use a static list
    # Also consider adding Russell 2000 for small-cap coverage

def ingest_company(symbol: str, cik: str = None):
    """
    Full ingestion for a single company:
    1. Fetch profile from yfinance → upsert into companies table
    2. Fetch EDGAR facts using CIK → parse into annual financials → upsert
    3. Fetch daily prices from yfinance → upsert
    4. Run Graham + Fisher scoring on the financials → upsert into scores
    5. Run valuation models → store composite intrinsic value in scores
    """

def bulk_ingest(symbols: list[str], skip_existing: bool = True):
    """
    Ingest a list of symbols. If skip_existing=True, skip companies
    whose data was fetched within the last 90 days.

    Shows progress bar and handles errors gracefully (log and continue).
    """

def refresh_prices(symbols: list[str] = None):
    """
    Quick refresh: update only prices and market cap for all companies
    (or specified list). Much faster than full ingestion.
    Does not re-fetch EDGAR data or re-run full analysis.
    """

def refresh_scores(symbols: list[str] = None):
    """
    Recompute Graham, Fisher, and valuation scores for all companies
    using existing data in the database. No API calls needed.
    """
```

**Usage from command line:**
```bash
# Initial bulk load (will take 30-60 minutes for 500 companies)
python -m ingestion.bulk_ingest --universe sp500

# Add a specific company
python -m ingestion.bulk_ingest --symbols AAPL,MSFT,KO

# Quick price refresh (daily, takes ~5 minutes for 500 companies)
python -m ingestion.bulk_ingest --refresh-prices

# Recompute all scores without fetching new data
python -m ingestion.bulk_ingest --refresh-scores
```

**Important:** Add `if __name__ == "__main__":` with argparse so this can be run
as a standalone script AND imported by the Flask app.

Test: Ingest 5 companies (AAPL, KO, JNJ, PG, WMT). Verify all tables populated.

### Step 5: Update Flask routes to use local DB

Modify `app.py` to query SQLite instead of FMP. FMP calls become optional fallback.

**Updated route logic:**

`/api/screen` — Query the `companies` + `scores` tables directly. Support filters:
  - `sector` — filter by sector
  - `capMin`, `capMax` — filter by market cap
  - `grahamGrade` — filter by Graham grade (A, B, C, D)
  - `minGrahamScore` — filter by minimum Graham percentage score
  - `fisherGrade` — filter by Fisher grade
  - `signal` — filter by valuation signal (STRONG BUY, BUY, etc.)
  - `minDiscount` — filter by minimum discount to intrinsic value
  - `sortBy` — sort by any score or metric
  - `limit` — default 50

  This is now a pure database query — zero API calls, instant results.

`/api/analyze/<symbol>` — First check the DB. If company exists and data
  is fresh (< 90 days), return from DB. If not, trigger a single-company
  ingestion, then return the results. This way the first analysis of a new
  company is slow (fetches data) but subsequent ones are instant.

`/api/backtest/<symbol>` — Pull prices and financials from DB.
  Only fetch from yfinance if not enough price history exists locally.

**New routes:**

`/api/ingest` (POST) — Trigger ingestion for specific symbols or a preset universe.
  Useful for the frontend to have an "Update Data" button.
  ```json
  POST /api/ingest
  {"symbols": ["AAPL", "MSFT"]}
  ```

`/api/db/stats` (GET) — Return database statistics:
  how many companies, how many with scores, date ranges, etc.
  Useful for a "Data Status" indicator in the UI.

`/api/screen/export` (GET) — Same filters as /api/screen but returns CSV for download.

### Step 6: Update Screener frontend

The screener becomes a powerful filtering tool. Replace the current sector-list approach.

**New Screener UI should have:**

Filter controls (top of page):
- Sector dropdown (All, Consumer Defensive, Utilities, etc.)
- Market Cap range dropdown
- Graham Grade dropdown (All, A, B, C, D) — NEW
- Fisher Grade dropdown (All, A, B, C, D) — NEW
- Signal dropdown (All, STRONG BUY, BUY, HOLD, OVERVALUED, STRONG SELL) — NEW
- Min Discount slider or input (e.g. "show only stocks trading 20%+ below intrinsic value") — NEW
- Sort By dropdown (Graham Score, Fisher Score, Discount, Market Cap, etc.) — NEW

Results table (shows immediately from DB, no loading needed):
- Symbol, Company Name, Sector, Market Cap, Price
- Graham Grade, Fisher Grade — NEW
- Intrinsic Value, Discount %, Signal — NEW

Each row still clickable to go to full Analysis view.

**Also add a "Data Status" indicator** somewhere in the UI showing:
- How many companies are in the database
- When data was last updated
- A button to trigger a price refresh or full re-ingestion

### Step 7: Update requirements.txt and README

```
# requirements.txt additions:
yfinance>=0.2.31
```

sqlite3 is part of Python stdlib — no install needed.

Update README with:
- New setup step: initial data ingestion (`python -m ingestion.bulk_ingest --universe sp500`)
- Explain that first run takes 30-60 minutes but subsequent use is instant
- Document new screener capabilities
- Note that FMP API key is now optional (only needed as fallback)

---

## Key Design Decisions

1. **SQLite over PostgreSQL** — No extra install, zero config, single file. Perfect for
   a local tool. Can migrate to Postgres later if needed.

2. **Pre-computed scores** — Graham and Fisher scores are computed at ingestion time and
   stored in the `scores` table. The screener queries pre-computed scores instead of
   recalculating on every request. Scores are refreshed when financials are updated.

3. **EDGAR as primary, yfinance as supplement** — EDGAR has the most authoritative and
   complete financial data. yfinance provides what EDGAR doesn't: current prices, profiles,
   sector/industry classification, and fast historical price data.

4. **Incremental updates** — The system tracks when each piece of data was last fetched.
   Full financial data (EDGAR) only needs refreshing quarterly. Prices can be refreshed
   daily. Scores are recomputed whenever underlying data changes.

5. **FMP becomes optional** — Keep the existing FMP integration as a fallback. If someone
   wants to analyze a company not yet in the DB and doesn't want to wait for EDGAR
   ingestion, FMP can fill in. But it's no longer the primary path.

---

## SEC EDGAR Gotchas & Tips

- **User-Agent is required.** SEC will block you without one. Use format: "AppName email@example.com"
- **Rate limit: 10 req/sec.** Respect this — SEC will ban your IP if you don't.
- **CIK is zero-padded to 10 digits.** Apple is CIK 320193, but the URL needs "0000320193".
- **XBRL taxonomy is messy.** Companies use different tags for the same concept. The field mapping
  in this spec covers the most common ones, but you'll encounter outliers. Log them and expand
  the mapping over time.
- **10-K vs 10-Q:** Annual filings are 10-K, quarterly are 10-Q. For our purposes, start with
  10-K only (annual data). Quarterly can be added later.
- **Fiscal year ≠ calendar year.** Some companies have fiscal years ending in June, September, etc.
  Use the `end` date from the filing period, not the filing date.
- **Restated data:** A company might file a 10-K in 2024 that restates 2023 numbers. Use the most
  recently filed value for each fiscal year.
