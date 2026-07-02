"""Cross-company strategy backtest (Completeness/Backtest spec, Part 2).

Tests the value-investing strategy across every company in the DB,
historically. For each backtest year we re-score every company using only
data that existed at that time (financials truncated to <= year Y, IV from
the historical_valuations table, price = average traded price during year Y),
then run an annual buy/hold/sell simulation with equal-weight position sizing.

No API calls: everything comes from SQLite. The one exception is auto-ingesting
SPY prices for the benchmark, done once on demand.

Strategy (Marco's definition):
  Quality gate (must pass ALL):
    - (Graham grade >= B AND Fisher grade >= B) OR (one is A and the other >= C)
    - IV trend is "growing"
    - data completeness >= min_completeness
  Entry: buy when price is below composite IV by more than margin_of_safety.
  Exit:  sell when price is above composite IV by more than sell_premium.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

from analysis.graham import score_graham
from analysis.fisher import score_fisher
from analysis.iv_trends import _avg_price_for_year, compute_iv_growth_rate
from ingestion.db_adapter import to_analysis_inputs

log = logging.getLogger(__name__)

BENCHMARK_SYMBOL = "SPY"
_GRADE_RANK = {"A": 4, "B": 3, "C": 2, "D": 1}
RISK_FREE_RATE = 0.02  # annual, for Sharpe


# ----------------------------- data prep helpers -----------------------------

def _quality_ok(graham_grade: Optional[str], fisher_grade: Optional[str]) -> bool:
    """(Graham B+ AND Fisher B+) OR (one A and the other C+)."""
    g = _GRADE_RANK.get(graham_grade, 0)
    f = _GRADE_RANK.get(fisher_grade, 0)
    if g == 0 or f == 0:
        return False
    both_b = g >= 3 and f >= 3
    one_a_other_c = (g == 4 and f >= 2) or (f == 4 and g >= 2)
    return both_b or one_a_other_c


def _load_company_bundle(symbol: str) -> Optional[dict]:
    """Everything needed to backtest one company, loaded once:
    company row, all financials (asc by year), daily prices, and the stored
    historical composite IV per year.
    """
    from database import models

    company = models.get_company(symbol)
    financials = models.get_financials(symbol, limit=40)
    if not company or not financials:
        return None

    prices = models.get_daily_prices(symbol)
    if not prices:
        return None

    # Composite IV per fiscal year from stored historical valuations.
    hv = models.get_historical_valuations(symbol)
    iv_by_year: dict[int, float] = {}
    positives: dict[int, list[float]] = defaultdict(list)
    for row in hv:
        val = row.get("intrinsic_value")
        if val is not None and val > 0:
            positives[row["fiscal_year"]].append(val)
    for yr, vals in positives.items():
        iv_by_year[yr] = sum(vals) / len(vals)

    return {
        "company": company,
        "financials": sorted(financials, key=lambda f: f["fiscal_year"]),
        "prices": prices,
        "iv_by_year": iv_by_year,
    }


def _score_as_of(bundle: dict, year: int) -> Optional[dict]:
    """Re-score a company as of `year` using only data <= year.

    Returns a dict with grades, completeness, composite IV, and avg price for
    that year, or None if the company can't be evaluated that year.
    """
    fins_through = [f for f in bundle["financials"] if f["fiscal_year"] <= year]
    if len(fins_through) < 2:
        return None

    avg_price = _avg_price_for_year(bundle["prices"], year)
    if avg_price is None or avg_price <= 0:
        return None

    iv = bundle["iv_by_year"].get(year)
    if iv is None or iv <= 0:
        return None

    # Re-run the engines on the truncated, most-recent-first statement lists.
    # Guard against pathological financials (e.g. negative revenue producing
    # complex growth rates) crashing the whole backtest — skip that
    # company-year instead.
    fins_desc = list(reversed(fins_through))
    inputs = to_analysis_inputs(bundle["company"], fins_desc)
    try:
        graham = score_graham(
            inputs["profile"], inputs["income"], inputs["balance"],
            inputs["cashflow"], inputs["key_metrics"],
        )
        fisher = score_fisher(
            inputs["profile"], inputs["income"], inputs["balance"], inputs["cashflow"],
        )
    except Exception:
        log.debug("[%s] scoring failed for year %s; skipping",
                  bundle["company"].get("symbol"), year, exc_info=True)
        return None

    # IV trend "as of" year Y: growth of composite IV up to Y.
    hist = [
        {"fiscal_year": y, "composite": v}
        for y, v in sorted(bundle["iv_by_year"].items()) if y <= year
    ]
    growth = compute_iv_growth_rate(hist)

    completeness = min(
        graham.get("dataCompleteness") or 0.0,
        fisher.get("dataCompleteness") or 0.0,
    )

    return {
        "graham_grade": graham.get("grade"),
        "fisher_grade": fisher.get("grade"),
        "completeness": completeness,
        "iv": iv,
        "avg_price": avg_price,
        "iv_trend": growth.get("trend"),
    }


# ----------------------------- benchmark -----------------------------

def _ensure_spy_prices() -> list[dict]:
    """Return SPY daily prices, auto-ingesting them once if absent."""
    from database import models

    prices = models.get_daily_prices(BENCHMARK_SYMBOL)
    if prices:
        return prices
    log.info("SPY prices missing — ingesting for benchmark")
    try:
        from ingestion import yfinance_fetcher as yfx
        rows = yfx.fetch_daily_prices(BENCHMARK_SYMBOL, start="2010-01-01")
        if rows:
            models.upsert_daily_prices(BENCHMARK_SYMBOL, rows)
    except Exception:
        log.exception("SPY ingest failed; benchmark will be unavailable")
    return models.get_daily_prices(BENCHMARK_SYMBOL)


def _benchmark_series(start_year: int, end_year: int) -> dict[int, float]:
    """Average SPY price per year over the range."""
    prices = _ensure_spy_prices()
    out: dict[int, float] = {}
    for year in range(start_year, end_year + 1):
        p = _avg_price_for_year(prices, year)
        if p is not None:
            out[year] = p
    return out


# ----------------------------- the backtest -----------------------------

def run_strategy_backtest(
    margin_of_safety: float = 0.30,
    sell_premium: float = 0.20,
    start_year: int = 2015,
    end_year: int = 2025,
    starting_capital: float = 100_000,
    max_positions: int = 20,
    min_completeness: float = 0.70,
    universe: Optional[list[str]] = None,
) -> dict:
    """Backtest the strategy across all scored companies. See module docstring."""
    from database import models

    if universe is None:
        # Only companies that have stored historical valuations can be
        # evaluated historically.
        from database.db import get_db
        rows = get_db().execute(
            "SELECT DISTINCT symbol FROM historical_valuations ORDER BY symbol"
        ).fetchall()
        universe = [r["symbol"] for r in rows]

    # Pre-load every company's data once.
    bundles: dict[str, dict] = {}
    for sym in universe:
        b = _load_company_bundle(sym)
        if b is not None:
            bundles[sym] = b
    log.info("strategy backtest: %d companies loaded", len(bundles))

    # Portfolio state.
    cash = starting_capital
    positions: dict[str, dict] = {}  # symbol -> {shares, buy_price, buy_iv, buy_year, buy_discount}
    all_trades: list[dict] = []
    yearly_data: list[dict] = []
    qualified_ever: set[str] = set()
    bought_ever: set[str] = set()
    evaluated: set[str] = set()

    peak_value = starting_capital
    max_drawdown = 0.0
    prev_value = starting_capital
    yearly_returns: list[float] = []

    years = list(range(start_year, end_year + 1))

    for year in years:
        # Score every company as of this year.
        scored_this_year: dict[str, dict] = {}
        for sym, bundle in bundles.items():
            s = _score_as_of(bundle, year)
            if s is None:
                continue
            evaluated.add(sym)
            scored_this_year[sym] = s

        # ---- SELL pass: exit holdings that are now overvalued ----
        sells = []
        for sym in list(positions.keys()):
            s = scored_this_year.get(sym)
            if s is None:
                continue  # can't price it this year; hold
            price = s["avg_price"]
            iv = s["iv"]
            premium = (price - iv) / iv if iv > 0 else None
            if premium is not None and premium > sell_premium:
                pos = positions.pop(sym)
                proceeds = pos["shares"] * price
                cash += proceeds
                ret = (price - pos["buy_price"]) / pos["buy_price"] if pos["buy_price"] else 0.0
                trade = {
                    "symbol": sym,
                    "buyYear": pos["buy_year"],
                    "buyPrice": round(pos["buy_price"], 2),
                    "buyIV": round(pos["buy_iv"], 2),
                    "buyDiscount": round(pos["buy_discount"], 3),
                    "sellYear": year,
                    "sellPrice": round(price, 2),
                    "sellIV": round(iv, 2),
                    "returnPct": round(ret, 3),
                    "holdingYears": year - pos["buy_year"],
                }
                all_trades.append(trade)
                sells.append(sym)

        # ---- BUY pass: qualifying, undervalued, room for more positions ----
        # Rank candidates by discount (deepest first).
        candidates = []
        for sym, s in scored_this_year.items():
            if sym in positions:
                continue
            if s["completeness"] < min_completeness:
                continue
            if s["iv_trend"] != "growing":
                continue
            if not _quality_ok(s["graham_grade"], s["fisher_grade"]):
                continue
            qualified_ever.add(sym)
            iv, price = s["iv"], s["avg_price"]
            discount = (iv - price) / iv if iv > 0 else None
            if discount is not None and discount > margin_of_safety:
                candidates.append((discount, sym, s))
        candidates.sort(key=lambda c: c[0], reverse=True)

        buys = []
        for discount, sym, s in candidates:
            if len(positions) >= max_positions:
                break
            slots_left = max_positions - len(positions)
            if slots_left <= 0 or cash <= 0:
                break
            alloc = cash / slots_left  # equal-weight over remaining slots
            price = s["avg_price"]
            shares = int(alloc / price) if price > 0 else 0
            if shares <= 0:
                continue
            cost = shares * price
            cash -= cost
            positions[sym] = {
                "shares": shares, "buy_price": price, "buy_iv": s["iv"],
                "buy_year": year, "buy_discount": discount,
            }
            bought_ever.add(sym)
            buys.append({"symbol": sym, "price": round(price, 2),
                         "discount": round(discount, 3), "shares": shares})

        # ---- Mark portfolio to market (using this year's avg prices) ----
        holdings_value = 0.0
        for sym, pos in positions.items():
            s = scored_this_year.get(sym)
            mark = s["avg_price"] if s else pos["buy_price"]
            holdings_value += pos["shares"] * mark
        portfolio_value = cash + holdings_value

        # Drawdown + return tracking.
        peak_value = max(peak_value, portfolio_value)
        if peak_value > 0:
            dd = (portfolio_value - peak_value) / peak_value
            max_drawdown = min(max_drawdown, dd)
        year_ret = (portfolio_value - prev_value) / prev_value if prev_value > 0 else 0.0
        yearly_returns.append(year_ret)
        prev_value = portfolio_value

        yearly_data.append({
            "year": year,
            "portfolioValue": round(portfolio_value, 2),
            "cash": round(cash, 2),
            "positions": sorted(positions.keys()),
            "positionCount": len(positions),
            "qualifiedCount": sum(
                1 for s in scored_this_year.values()
                if s["completeness"] >= min_completeness
                and s["iv_trend"] == "growing"
                and _quality_ok(s["graham_grade"], s["fisher_grade"])
            ),
            "buys": buys,
            "sells": sells,
            "returnYTD": round(year_ret, 4),
        })

    ending_value = yearly_data[-1]["portfolioValue"] if yearly_data else starting_capital
    n_years = len(years)
    total_return = (ending_value - starting_capital) / starting_capital if starting_capital else 0.0
    annualized = ((ending_value / starting_capital) ** (1 / n_years) - 1) if n_years > 0 and starting_capital > 0 else 0.0

    # Benchmark (SPY total price return over the same window).
    bench = _benchmark_series(start_year, end_year)
    bench_return = None
    bench_annualized = None
    bench_series = []
    if bench:
        byears = sorted(bench)
        b_start, b_end = bench[byears[0]], bench[byears[-1]]
        if b_start > 0:
            bench_return = (b_end - b_start) / b_start
            bspan = byears[-1] - byears[0]
            if bspan > 0:
                bench_annualized = (b_end / b_start) ** (1 / bspan) - 1
        # Normalized benchmark value series starting at starting_capital.
        bench_series = [
            {"year": y, "value": round(starting_capital * bench[y] / b_start, 2)}
            for y in byears
        ]

    # Sharpe from yearly returns.
    sharpe = None
    if len(yearly_returns) >= 2:
        mean_r = sum(yearly_returns) / len(yearly_returns)
        var = sum((r - mean_r) ** 2 for r in yearly_returns) / (len(yearly_returns) - 1)
        std = var ** 0.5
        if std > 0:
            sharpe = (mean_r - RISK_FREE_RATE) / std

    # Trade stats.
    wins = [t for t in all_trades if t["returnPct"] > 0]
    win_rate = len(wins) / len(all_trades) if all_trades else None
    avg_hold = (sum(t["holdingYears"] for t in all_trades) / len(all_trades)) if all_trades else None

    return {
        "params": {
            "marginOfSafety": margin_of_safety,
            "sellPremium": sell_premium,
            "startYear": start_year,
            "endYear": end_year,
            "startingCapital": starting_capital,
            "maxPositions": max_positions,
            "minCompleteness": min_completeness,
        },
        "summary": {
            "startingCapital": starting_capital,
            "endingValue": round(ending_value, 2),
            "totalReturn": round(total_return, 4),
            "annualizedReturn": round(annualized, 4),
            "benchmarkReturn": round(bench_return, 4) if bench_return is not None else None,
            "benchmarkAnnualized": round(bench_annualized, 4) if bench_annualized is not None else None,
            "alpha": round(annualized - bench_annualized, 4) if bench_annualized is not None else None,
            "sharpeRatio": round(sharpe, 3) if sharpe is not None else None,
            "maxDrawdown": round(max_drawdown, 4),
            "totalTrades": len(all_trades),
            "winRate": round(win_rate, 3) if win_rate is not None else None,
            "avgHoldingPeriod": round(avg_hold, 2) if avg_hold is not None else None,
            "companiesEvaluated": len(evaluated),
            "companiesQualified": len(qualified_ever),
            "companiesBought": len(bought_ever),
        },
        "yearlyData": yearly_data,
        "allTrades": all_trades,
        "benchmarkSeries": bench_series,
    }


def run_parameter_sweep(
    mos_values: Optional[list[float]] = None,
    sell_values: Optional[list[float]] = None,
    start_year: int = 2015,
    end_year: int = 2025,
    **kwargs,
) -> list[dict]:
    """Run the backtest for every (margin_of_safety, sell_premium) combo.

    Returns a list of {marginOfSafety, sellPremium, ...summary fields} dicts.
    Loads company bundles once and reuses them across combos for speed by
    passing a shared universe.
    """
    if mos_values is None:
        mos_values = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
    if sell_values is None:
        sell_values = [0.10, 0.15, 0.20, 0.30]

    results = []
    for mos in mos_values:
        for sell in sell_values:
            res = run_strategy_backtest(
                margin_of_safety=mos, sell_premium=sell,
                start_year=start_year, end_year=end_year, **kwargs,
            )
            s = res["summary"]
            results.append({
                "marginOfSafety": mos,
                "sellPremium": sell,
                "totalReturn": s["totalReturn"],
                "annualizedReturn": s["annualizedReturn"],
                "sharpeRatio": s["sharpeRatio"],
                "maxDrawdown": s["maxDrawdown"],
                "totalTrades": s["totalTrades"],
                "winRate": s["winRate"],
                "endingValue": s["endingValue"],
            })
    return results
