"""Historical intrinsic-value trends (Phase 3, Part 2).

Re-runs the five Phase 2 valuation models for each historical fiscal year
"as if" that year were the present, so we can see whether a company's
intrinsic value is growing, flat, or declining.

Key mechanics (why this is fiddly):

* The valuation engine derives share count from `marketCap / price` in the
  profile, NOT from weighted-average-shares in the statements. To value a
  company as of year Y we therefore synthesize a profile whose price is the
  *average traded price during year Y* and whose marketCap is
  `price_Y * shares_Y`, where shares_Y is that year's weighted-average share
  count. That makes the engine's implied share count period-correct.

* Growth-based models (Graham, DCF) read `income[0]`/`income[-1]` and
  `cashflow[0]`/`cashflow[-1]`. Standing in year Y, we only feed statements
  from year Y and earlier, most-recent-first, so `[0]` is year Y and `[-1]`
  is the oldest available year — i.e. only data knowable at year Y.

* EPV averages net income over whatever years it is handed. The spec wants
  a 5-year trailing average ending in Y, so we slice the trailing 5 years.

This module does NOT modify the analysis engines; it feeds them
reconstructed inputs via the same FMP-shaped dicts the db_adapter produces.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

from analysis import valuation as val
from ingestion.db_adapter import (
    _income_row, _balance_row, _cashflow_row,
)

log = logging.getLogger(__name__)

MODELS = ("graham", "dcf", "book_value", "epv", "ncav")
EPV_TRAILING_YEARS = 5


# ----------------------------- price helpers -----------------------------

def _avg_price_for_year(daily_prices: list[dict], year: int) -> Optional[float]:
    """Average close during the calendar year matching `year`.

    daily_prices rows have "date" (YYYY-MM-DD) and "close". Returns None if
    no bars fall in that year.
    """
    closes = []
    prefix = f"{year}-"
    for r in daily_prices:
        d = r.get("date") or ""
        if d.startswith(prefix):
            c = r.get("close")
            if c is not None and not (isinstance(c, float) and math.isnan(c)):
                closes.append(c)
    if not closes:
        return None
    return sum(closes) / len(closes)


def _shares_for_year(fin: dict) -> Optional[float]:
    """Best available share count for a fiscal year: weighted avg diluted,
    else basic. None if neither is present/positive."""
    for key in ("weighted_avg_shares_diluted", "weighted_avg_shares"):
        v = fin.get(key)
        if v and v > 0:
            return v
    return None


# ----------------------------- per-year valuation -----------------------------

def _synth_profile(company: dict, avg_price: float, shares: float) -> list[dict]:
    """FMP-style single-element profile list with a historical price/mktcap.

    marketCap = avg_price * shares so the engine's implied share count
    (marketCap/price) equals `shares` for that year.
    """
    return [{
        "symbol": company.get("symbol"),
        "companyName": company.get("name"),
        "sector": company.get("sector"),
        "industry": company.get("industry"),
        "price": avg_price,
        "marketCap": avg_price * shares,
    }]


def _valuation_for_year(company: dict, fins_through_year: list[dict],
                        avg_price: float) -> dict:
    """Run the 5 models as of the most-recent year in `fins_through_year`.

    fins_through_year: financials rows, MOST RECENT FIRST, containing only
    year Y and earlier. avg_price: average traded price during year Y.
    """
    latest = fins_through_year[0]
    shares = _shares_for_year(latest)
    models_out: dict[str, dict] = {}

    profile = _synth_profile(company, avg_price, shares) if shares else [{
        "symbol": company.get("symbol"), "price": avg_price, "marketCap": None,
    }]

    income = [_income_row(f) for f in fins_through_year]
    balance = [_balance_row(f) for f in fins_through_year]
    cashflow = [_cashflow_row(f) for f in fins_through_year]

    # Graham (EPS growth up to year Y)
    g = val.graham_formula(income, profile)
    if g:
        models_out["graham"] = {"intrinsic_value": g["intrinsicValue"], "inputs": g["inputs"]}

    # DCF (FCF growth up to year Y)
    d = val.simplified_dcf(cashflow, profile)
    if d:
        models_out["dcf"] = {"intrinsic_value": d["intrinsicValue"], "inputs": d["inputs"]}

    # Book value (year Y equity)
    b = val.book_value(balance, profile)
    if b:
        models_out["book_value"] = {"intrinsic_value": b["intrinsicValue"], "inputs": b["inputs"]}

    # EPV — 5-year trailing average ending in Y
    epv_income = income[:EPV_TRAILING_YEARS]
    e = val.earnings_power_value(epv_income, profile)
    if e:
        models_out["epv"] = {"intrinsic_value": e["intrinsicValue"], "inputs": e["inputs"]}

    # NCAV (year Y balance sheet)
    n = val.ncav_value(balance, profile)
    if n:
        models_out["ncav"] = {"intrinsic_value": n["intrinsicValue"], "inputs": n["inputs"]}

    # Composite: average of positive model values (matches valuation.py)
    positives = [m["intrinsic_value"] for m in models_out.values()
                 if m["intrinsic_value"] is not None and m["intrinsic_value"] > 0]
    composite = round(sum(positives) / len(positives), 2) if positives else None

    return {"models": models_out, "composite": composite}


def compute_historical_valuations(symbol: str, financials: list[dict],
                                   profile: dict,
                                   daily_prices: Optional[list[dict]] = None) -> list[dict]:
    """For each fiscal year, compute intrinsic value under all 5 models as if
    that year were the present.

    Args:
        symbol: ticker (used only for logging).
        financials: `financials` rows for the company, any order (we sort).
        profile: the `companies` row (snake_case). Provides name/sector.
        daily_prices: `daily_prices` rows for the company. If omitted, they
            are loaded from the DB.

    Returns a list (oldest year first) of:
        {"fiscal_year", "avg_price", "models": {model: {...}}, "composite"}
    """
    if not financials:
        return []

    if daily_prices is None:
        from database import models as _m
        daily_prices = _m.get_daily_prices(symbol)

    # Sort ascending by fiscal year; we need at least 2 years for growth models.
    fins_asc = sorted(financials, key=lambda f: f["fiscal_year"])
    out: list[dict] = []

    for idx, fin in enumerate(fins_asc):
        year = fin["fiscal_year"]
        # Only data knowable at year Y: year Y and earlier, MOST RECENT FIRST.
        through_year = fins_asc[: idx + 1][::-1]
        if len(through_year) < 2:
            # Growth models need >= 2 years; skip the very first year but still
            # attempt point-in-time models (book/ncav) if a price exists.
            pass

        avg_price = _avg_price_for_year(daily_prices, year)
        if avg_price is None:
            # No price that year -> we can't anchor share count; skip.
            continue

        result = _valuation_for_year(profile, through_year, avg_price)
        out.append({
            "fiscal_year": year,
            "avg_price": round(avg_price, 2),
            "models": result["models"],
            "composite": result["composite"],
        })

    return out


# ----------------------------- growth / trend -----------------------------

def compute_iv_growth_rate(historical_valuations: list[dict]) -> dict:
    """CAGR + trend classification + stability (R^2 of log-linear fit).

    historical_valuations: output of compute_historical_valuations (oldest
    first). Uses the `composite` series, ignoring years where composite is
    None or non-positive (log undefined).
    """
    empty = {
        "cagr_5yr": None, "cagr_10yr": None, "trend": None,
        "stability": None, "recent_direction": None,
    }
    if not historical_valuations:
        return empty

    series = [
        (h["fiscal_year"], h["composite"])
        for h in historical_valuations
        if h.get("composite") is not None and h["composite"] > 0
    ]
    if len(series) < 2:
        return empty

    series.sort(key=lambda x: x[0])

    def _cagr(years_back: int) -> Optional[float]:
        # Find endpoints spanning ~years_back years.
        end_year, end_val = series[-1]
        target = end_year - years_back
        # Pick the earliest point at or after target that leaves a span.
        start = None
        for y, v in series:
            if y <= target:
                start = (y, v)
            else:
                break
        # If nothing at/older than target, fall back to the oldest point.
        if start is None:
            start = series[0]
        start_year, start_val = start
        span = end_year - start_year
        if span <= 0 or start_val <= 0:
            return None
        return round((end_val / start_val) ** (1 / span) - 1, 4)

    cagr_5 = _cagr(5)
    cagr_10 = _cagr(10)

    # Stability: R^2 of ln(composite) vs year (how steady the growth is).
    xs = [y for y, _ in series]
    ys = [math.log(v) for _, v in series]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    syy = sum((y - mean_y) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        stability = None
        slope = 0.0
    else:
        slope = sxy / sxx
        r = sxy / math.sqrt(sxx * syy)
        stability = round(r * r, 4)

    # Trend from the primary CAGR (5yr if available else 10yr else slope sign).
    primary = cagr_5 if cagr_5 is not None else cagr_10
    if primary is not None:
        if primary > 0.02:
            trend = "growing"
        elif primary < -0.02:
            trend = "declining"
        else:
            trend = "stable"
    else:
        trend = "growing" if slope > 0 else ("declining" if slope < 0 else "stable")

    # Recent direction: last vs prior composite.
    recent_direction = None
    if len(series) >= 2:
        recent_direction = "up" if series[-1][1] >= series[-2][1] else "down"

    return {
        "cagr_5yr": cagr_5,
        "cagr_10yr": cagr_10,
        "trend": trend,
        "stability": stability,
        "recent_direction": recent_direction,
    }
