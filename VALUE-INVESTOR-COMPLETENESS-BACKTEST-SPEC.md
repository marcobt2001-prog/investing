# Data Completeness + Cross-Company Strategy Backtest

## Part 1: Data Completeness Scoring

### The Problem

When EDGAR data is missing for a particular field (e.g. R&D expense, SGA, current
assets), the Graham and Fisher engines score that criterion as 0. This means "data
not found" is treated the same as "company failed the test." That's misleading — a
company with 6 out of 9 Graham criteria passing and 3 criteria with missing data
gets the same grade as a company that genuinely failed 3 criteria. The scores are
biased downward for companies with incomplete XBRL coverage.

### The Solution

Track which inputs were actually available for each criterion. Report a completeness
percentage alongside the scores. Flag companies below 80% completeness so the user
knows the score is unreliable — but don't hide them.

### Changes to `analysis/graham.py`

The `score_graham()` function currently returns:
```python
{
    "scores": {"adequateSize": 1.0, "currentRatio": 0.5, ...},
    "details": {...},
    "totalScore": 6.5,
    "maxScore": 9,
    "pctScore": 0.722,
    "grade": "B"
}
```

Add a `"dataAvailable"` dict that mirrors `"scores"` but with True/False for each
criterion, indicating whether the required input data existed.

**Criterion → required data mapping:**

| Criterion | Required Fields | Source |
|---|---|---|
| adequateSize | revenue | income[0] |
| currentRatio | totalCurrentAssets, totalCurrentLiabilities | balance[0] |
| debtToEquity | totalDebt, totalStockholdersEquity | balance[0] |
| earningsStability | netIncome (for each of last 10 years) | income[0:10] |
| earningsGrowth | netIncome (need at least 10 years) | income[0:10] |
| moderatePE | eps or netIncome, price | income[0], profile |
| moderatePB | totalStockholdersEquity, price, shares | balance[0], profile |
| dividendRecord | dividendsPaid (for each of last 5 years) | cashflow[0:5] |
| ncav | totalCurrentAssets, totalLiabilities, shares, price | balance[0], profile |

**Implementation approach:**

For each criterion, BEFORE computing the score, check if the required fields are
present and non-None. Set `dataAvailable[criterion] = True/False` accordingly.

When a required field is missing, still set the score to 0 (don't change the scoring
logic), but mark `dataAvailable` as False.

Add to the return dict:
```python
{
    "scores": {...},
    "details": {...},
    "dataAvailable": {
        "adequateSize": True,
        "currentRatio": True,
        "debtToEquity": False,   # totalDebt was None
        "earningsStability": True,
        "earningsGrowth": False, # fewer than 10 years of data
        "moderatePE": True,
        "moderatePB": True,
        "dividendRecord": False, # no cashflow data
        "ncav": True,
    },
    "dataCompleteness": 0.667,  # 6 of 9 criteria had data
    "completenessNote": "3 of 9 criteria could not be evaluated due to missing data",
    "totalScore": 6.5,
    "maxScore": 9,
    "adjustedPctScore": 0.929,  # 6.5 / 7 (only count criteria with data)
    "pctScore": 0.722,          # original: 6.5 / 9 (all criteria)
    "grade": "B",               # still uses pctScore (unadjusted) for conservative grading
}
```

The `adjustedPctScore` divides the total score by only the criteria that had data,
giving a fairer picture of how the company performs on the tests we *could* run.
The `grade` still uses the unadjusted `pctScore` to stay conservative.

### Changes to `analysis/fisher.py`

Same pattern. Fisher already has `manualReviewCount` for criteria that need human
review. Now add `dataAvailable` for the automated criteria.

**Fisher criterion → required data:**

| Criterion | Required Fields |
|---|---|
| salesGrowth | revenue (at least 2 years) |
| rdCommitment | researchAndDevelopmentExpenses, revenue |
| rdEffectiveness | grossProfit, revenue (at least 3 years) |
| salesEfficiency | sellingGeneralAndAdministrativeExpenses, revenue |
| profitMargin | operatingIncome, revenue |
| marginImprovement | operatingIncome, revenue (at least 3 years) |
| laborRelations | sellingGeneralAndAdministrativeExpenses, revenue (at least 3 years) |
| execRelations | netIncome, totalStockholdersEquity (at least 3 years) |
| accounting | netIncome, operatingCashFlow, totalAssets |
| longRangeProfit | freeCashFlow, revenue (at least 3 years) |
| dilution | weightedAverageShsOut (at least 3 years) |

Manual review items (mgmtDepth, industryAspects, mgmtComms, mgmtIntegrity) should
have `dataAvailable: null` — they're not data-dependent, they're judgment-dependent.

Add `dataCompleteness` and `adjustedPctScore` to the Fisher return dict too.

**Special case for R&D:** Some industries (consumer staples, banks, utilities)
legitimately have zero R&D spending. If `researchAndDevelopmentExpenses` is 0 (not
None/missing), that's data available = True, not missing. Only mark as unavailable
if the field is None.

### Changes to `scores` table

Add two new columns:
```sql
ALTER TABLE scores ADD COLUMN graham_completeness REAL;
ALTER TABLE scores ADD COLUMN fisher_completeness REAL;
```

### Changes to `bulk_ingest.py` → `compute_and_store_scores()`

After computing graham and fisher scores, also store the completeness values:
```python
score_payload["graham_completeness"] = graham.get("dataCompleteness")
score_payload["fisher_completeness"] = fisher.get("dataCompleteness")
```

### Changes to screener

**Backend (`models.py` → `screen_companies()`):**
Add optional filter parameters:
- `minGrahamCompleteness` (default: None, no filter)
- `minFisherCompleteness` (default: None, no filter)

**Backend (`app.py` → `/api/screen`):**
Accept `minGrahamCompleteness` and `minFisherCompleteness` query params.

**Frontend (`Screener.jsx`):**
- Add a "Min Data Completeness" dropdown with options: All, 60%+, 70%+, 80%+, 90%+
  This filters on `MIN(graham_completeness, fisher_completeness)`.
- In the results table, add a "Data" column showing the lower of the two
  completeness percentages. Color-code it:
  - Green (≥ 80%): scores are reliable
  - Amber (60-80%): scores may be unreliable, some criteria missing
  - Red (< 60%): significant data gaps, treat scores with caution
- Do NOT hide low-completeness companies by default. Just show the indicator.

**Frontend (`Analysis.jsx`):**
- In the Graham Criteria Breakdown, for each criterion where `dataAvailable` is False,
  show a different visual indicator — maybe a gray dot with "No Data" instead of the
  red dot with "0.0" that currently displays. This makes it immediately obvious which
  scores are real fails vs data gaps.
- Same for Fisher checklist.
- Show a completeness summary at the top: "Graham: 7/9 criteria evaluable (78%)"

### Testing

After implementing, run `--refresh-scores` to recompute all scores with the new
completeness tracking. Then:
1. Check a well-known company like AAPL — should have 90%+ completeness.
2. Check a smaller company that had missing data errors — completeness should be lower.
3. Verify the screener's completeness filter works.
4. Verify the Analysis page shows "No Data" vs "Failed" visually.

---

## Part 2: Cross-Company Strategy Backtest

### The Problem

The existing backtest works on a single company at a time. Marco wants to test his
overall investment strategy across ALL companies in the database to see if the
screening criteria actually predict returns.

### Marco's Strategy Definition

**Stock selection criteria (must meet ALL):**
- Option A: Graham grade B or better AND Fisher grade B or better
- Option B: One grade is A AND the other is C or better
- IV trend is "growing"

**Entry rule:** Buy when the stock trades at a discount to composite intrinsic value
greater than the margin of safety threshold.

**Exit rule:** Sell when the stock trades at a premium to composite intrinsic value
greater than the sell premium threshold.

**Parameters to test:**
- Margin of safety: 15%, 20%, 25%, 30%, 35%, 40%
- Sell premium: 10%, 15%, 20%, 30%
- Starting capital: $100,000
- Position sizing: equal-weight (divide capital equally among qualifying stocks)
- Rebalance: annual (evaluate criteria once per year)

### New Analysis Module: `analysis/strategy_backtest.py`

```python
def run_strategy_backtest(
    margin_of_safety: float = 0.30,
    sell_premium: float = 0.20,
    start_year: int = 2015,
    end_year: int = 2025,
    starting_capital: float = 100_000,
    max_positions: int = 20,
    min_completeness: float = 0.70,
) -> dict:
    """
    Backtest Marco's value investing strategy across all companies in the DB.

    Annual loop:
    1. At the start of each year, pull all companies with scores computed.
    2. Filter to companies meeting the quality criteria:
       - (Graham B+ AND Fisher B+) OR (one A and other C+)
       - IV trend = "growing"
       - Data completeness ≥ min_completeness
    3. For qualifying companies, compute the discount to intrinsic value
       using that year's price and intrinsic value estimate.
    4. BUY: if discount > margin_of_safety and we have capital and room
       for more positions.
    5. SELL: if a held stock's premium > sell_premium (price exceeds IV
       by more than the threshold).
    6. HOLD: otherwise.
    7. Position sizing: equal-weight. When buying, allocate
       available_capital / (max_positions - current_positions).
    8. Track portfolio value = cash + sum(shares × price) each year.

    Computing historical scores:
    For each year Y in the backtest range, we need to know what Graham/Fisher
    grades the company WOULD have had using only data available at that time.
    We do this by:
    - Pulling financials up to year Y from the DB
    - Re-running score_graham and score_fisher on that subset
    - Using the historical intrinsic value from the historical_valuations table
    - Using the average stock price during year Y from daily_prices

    This is CPU-intensive (re-scoring every company for every year) but
    requires zero API calls — all data is already in SQLite.

    Returns:
    {
        "params": {
            "marginOfSafety": 0.30,
            "sellPremium": 0.20,
            "startYear": 2015,
            "endYear": 2025,
            "maxPositions": 20,
            "minCompleteness": 0.70,
        },
        "summary": {
            "totalReturn": 0.85,          # 85% total return
            "annualizedReturn": 0.064,     # 6.4% annualized
            "benchmarkReturn": 1.50,       # S&P 500 total return same period
            "benchmarkAnnualized": 0.096,  # S&P benchmark annualized
            "sharpeRatio": 0.72,           # (return - risk_free) / volatility
            "maxDrawdown": -0.25,          # worst peak-to-trough
            "totalTrades": 47,
            "winRate": 0.62,               # % of trades that were profitable
            "avgHoldingPeriod": 2.3,       # years
            "companiesEvaluated": 450,
            "companiesQualified": 83,      # met quality criteria at least once
            "companiesBought": 34,         # actually purchased (met MoS threshold)
        },
        "yearlyData": [
            {
                "year": 2015,
                "portfolioValue": 100000,
                "cash": 100000,
                "positions": [],
                "qualifiedCount": 12,
                "buys": [...],
                "sells": [...],
                "returnYTD": 0.0,
            },
            ...
        ],
        "allTrades": [
            {
                "symbol": "CINF",
                "buyYear": 2016,
                "buyPrice": 54.30,
                "buyIV": 78.50,
                "buyDiscount": 0.308,
                "sellYear": 2019,
                "sellPrice": 95.20,
                "sellIV": 82.10,
                "returnPct": 0.753,
                "holdingYears": 3,
            },
            ...
        ],
        "positionHistory": {
            # For each symbol that was ever held, the years it was in the portfolio
            "CINF": {"entryYear": 2016, "exitYear": 2019, "return": 0.753},
            ...
        },
    }
    """
```

### Benchmark Comparison

To know if the strategy is any good, compare against a simple benchmark.
Use the S&P 500 (SPY) total return over the same period. This data should
already be in your daily_prices table — if not, auto-ingest SPY.

### Parameter Sweep

```python
def run_parameter_sweep(
    mos_values: list[float] = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40],
    sell_values: list[float] = [0.10, 0.15, 0.20, 0.30],
    start_year: int = 2015,
    end_year: int = 2025,
) -> list[dict]:
    """
    Run the strategy backtest for every combination of margin of safety
    and sell premium. Returns a list of summary dicts, one per parameter combo.

    Useful for finding which MoS/sell thresholds produce the best risk-adjusted
    returns. Present as a heatmap or table in the UI.
    """
```

### Flask Routes

```
POST /api/backtest/strategy
    Body: {
        "marginOfSafety": 0.30,
        "sellPremium": 0.20,
        "startYear": 2015,
        "endYear": 2025,
        "maxPositions": 20,
        "minCompleteness": 0.70
    }
    Returns the full backtest result.

POST /api/backtest/strategy/sweep
    Body: {
        "mosValues": [0.15, 0.20, 0.25, 0.30, 0.35],
        "sellValues": [0.10, 0.15, 0.20, 0.30],
        "startYear": 2015,
        "endYear": 2025
    }
    Returns array of summary results for each parameter combination.
```

### Frontend: New "Strategy Backtest" Section

Add this to the Backtest tab (or make it a sub-tab alongside the existing
single-company backtest).

**Controls:**
- Margin of Safety slider/dropdown (15% to 50%)
- Sell Premium slider/dropdown (10% to 30%)
- Start Year / End Year dropdowns
- Max Positions input (default 20)
- Min Data Completeness dropdown (default 70%)
- "Run Strategy Backtest" button
- "Run Parameter Sweep" button (runs all combinations)

**Results display:**

Summary cards (same style as existing backtest):
- Starting Capital, Ending Value, Total Return, Annualized Return
- Benchmark Return (S&P 500), Alpha (strategy return - benchmark)
- Max Drawdown, Win Rate, Avg Holding Period

Year-by-year table:
- Year, Portfolio Value, Cash, # Positions, # Buys, # Sells, YTD Return

Trade log:
- Symbol, Buy Year, Buy Price, Buy IV, Discount at Purchase,
  Sell Year, Sell Price, Return %, Holding Period

Parameter sweep results (if sweep was run):
- Table or heatmap showing annualized return for each MoS × Sell Premium combination
- Highlight the best-performing combination
- Show Sharpe ratio alongside return so the user sees risk-adjusted performance

**Chart:**
- Line chart: portfolio value over time vs S&P 500 benchmark
- Use recharts (already available)

---

## Build Order

### Step 1: Data completeness in Graham engine

1. Update `graham.py` to add `dataAvailable` dict and `dataCompleteness` metric.
2. Add `adjustedPctScore`.
3. Test: run on AAPL (should be high completeness) and a small company with gaps.
4. Do NOT change scoring behavior — just add the metadata.

### Step 2: Data completeness in Fisher engine

1. Same pattern as Graham.
2. Handle the R&D special case (0 is not the same as None).
3. Test same companies.

### Step 3: Wire completeness into scores table and screener

1. Add columns to scores table.
2. Update `compute_and_store_scores()` to store completeness values.
3. Update `screen_companies()` to accept completeness filters.
4. Update `/api/screen` route.
5. Run `--refresh-scores` to recompute all.
6. Test: verify screener can filter by completeness.

### Step 4: Frontend completeness display

1. Update Screener results table: add Data column with color-coded completeness %.
2. Update Analysis page: show "No Data" vs "Failed" for each criterion.
3. Add completeness filter dropdown to screener.

### Step 5: Strategy backtest engine

1. Implement `run_strategy_backtest()` in `analysis/strategy_backtest.py`.
2. Make sure SPY is in the database (auto-ingest if not).
3. Implement `run_parameter_sweep()`.
4. Test: run a single backtest with default params, verify output shape and sanity.

### Step 6: Strategy backtest routes and frontend

1. Add Flask routes for strategy backtest and parameter sweep.
2. Add UI controls and results display to the Backtest tab.
3. Add portfolio vs benchmark chart.
4. Add parameter sweep results table/heatmap.

### Step 7: Test end-to-end

1. Run the full strategy backtest. Does it produce reasonable results?
2. Run a parameter sweep. Does it complete without errors?
3. Verify the chart looks correct.
4. Spot-check a few trades in the trade log — do the buy/sell decisions
   match the criteria?
