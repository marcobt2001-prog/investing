"""yfinance wrapper for company profiles and daily price history.

EDGAR has the most complete financial-statement data; yfinance fills the
gaps EDGAR doesn't cover well: real-time price, market cap, sector/industry
classification, dividend yield, beta, and historical OHLCV.

yfinance has no official rate limit but will throttle aggressive callers.
We sleep briefly between requests in `bulk_ingest`. For multi-symbol price
fetches `yf.download(...)` is much faster than per-ticker calls — exposed
here as `fetch_daily_prices_bulk`.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Optional

import yfinance as yf

log = logging.getLogger(__name__)


def _none_if_nan(v):
    if v is None:
        return None
    try:
        if isinstance(v, float) and math.isnan(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def fetch_profile(symbol: str) -> Optional[dict]:
    """Fetch core company metadata. Returns None if the ticker is unknown
    or yfinance has no info for it.

    Output keys match the `companies` SQLite table columns. `dividend_yield`
    is normalized to a fraction (0.025 == 2.5%) — yfinance occasionally
    returns it as a percent already, so we sanity-clamp anything > 1.
    """
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
    except Exception as e:
        log.warning("[%s] yfinance profile fetch failed: %s", symbol, e)
        return None

    if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None:
        # yfinance returns a near-empty dict for invalid tickers
        if not info.get("longName") and not info.get("shortName"):
            log.warning("[%s] yfinance returned no profile data", symbol)
            return None

    div_yield = _none_if_nan(info.get("dividendYield"))
    # yfinance has been inconsistent: sometimes 0.025, sometimes 2.5. Normalize.
    if div_yield is not None and div_yield > 1:
        div_yield = div_yield / 100.0

    return {
        "symbol": symbol.upper(),
        "name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "market_cap": _none_if_nan(info.get("marketCap")),
        "price": _none_if_nan(info.get("currentPrice") or info.get("regularMarketPrice")),
        "shares_outstanding": _none_if_nan(info.get("sharesOutstanding")),
        "beta": _none_if_nan(info.get("beta")),
        "dividend_yield": div_yield,
        "exchange": info.get("exchange"),
        "description": info.get("longBusinessSummary"),
    }


def fetch_daily_prices(symbol: str, start: str = "2010-01-01", end: Optional[str] = None) -> list[dict]:
    """Fetch daily OHLCV bars from `start` (inclusive) to `end` (exclusive,
    defaults to today). Returns a list of dicts ready for upsert_daily_prices.

    Empty list if the ticker has no history or the request fails.
    """
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start, end=end, auto_adjust=False, actions=False)
    except Exception as e:
        log.warning("[%s] yfinance price fetch failed: %s", symbol, e)
        return []

    if df is None or df.empty:
        return []

    rows: list[dict] = []
    for idx, row in df.iterrows():
        date = idx.strftime("%Y-%m-%d")
        close = _none_if_nan(row.get("Close"))
        rows.append({
            "symbol": symbol.upper(),
            "date": date,
            "open": _none_if_nan(row.get("Open")),
            "high": _none_if_nan(row.get("High")),
            "low": _none_if_nan(row.get("Low")),
            "close": close,
            "adj_close": _none_if_nan(row.get("Adj Close")) or close,
            "volume": int(row["Volume"]) if not math.isnan(row.get("Volume", float("nan"))) else 0,
        })
    return rows


def fetch_daily_prices_bulk(
    symbols: list[str],
    start: str = "2010-01-01",
    end: Optional[str] = None,
) -> dict[str, list[dict]]:
    """Fetch OHLCV for many symbols in one shot using yf.download(...).

    Much faster than per-symbol calls when ingesting hundreds of tickers.
    Returns a {symbol: [rows]} map. Symbols with no data simply have an
    empty list.
    """
    if not symbols:
        return {}

    try:
        df = yf.download(
            tickers=symbols,
            start=start,
            end=end,
            auto_adjust=False,
            actions=False,
            group_by="ticker",
            progress=False,
            threads=True,
        )
    except Exception as e:
        log.warning("yf.download bulk failed: %s — falling back to per-ticker", e)
        return {s: fetch_daily_prices(s, start=start, end=end) for s in symbols}

    if df is None or df.empty:
        return {s: [] for s in symbols}

    out: dict[str, list[dict]] = {}
    # When a single symbol is passed, yf.download returns a flat frame; for
    # multiple it returns a multi-level column index keyed by ticker.
    if len(symbols) == 1:
        out[symbols[0].upper()] = _df_to_rows(df, symbols[0])
        return out

    for sym in symbols:
        try:
            sub = df[sym]
        except KeyError:
            out[sym.upper()] = []
            continue
        out[sym.upper()] = _df_to_rows(sub, sym)
    return out


def _df_to_rows(df, symbol: str) -> list[dict]:
    rows: list[dict] = []
    sym = symbol.upper()
    for idx, row in df.iterrows():
        # Skip fully-NaN rows (yf returns these for tickers that didn't trade)
        close = _none_if_nan(row.get("Close"))
        if close is None:
            continue
        vol = row.get("Volume")
        rows.append({
            "symbol": sym,
            "date": idx.strftime("%Y-%m-%d"),
            "open": _none_if_nan(row.get("Open")),
            "high": _none_if_nan(row.get("High")),
            "low": _none_if_nan(row.get("Low")),
            "close": close,
            "adj_close": _none_if_nan(row.get("Adj Close")) or close,
            "volume": int(vol) if vol is not None and not (isinstance(vol, float) and math.isnan(vol)) else 0,
        })
    return rows


# A small courtesy delay for callers that loop over symbols.
def polite_sleep(seconds: float = 0.5) -> None:
    time.sleep(seconds)
