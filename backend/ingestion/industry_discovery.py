"""Industry discovery + two-phase ingestion (Phase 3, Part 1).

Two ingestion depths:

  Light ingest  - profile only (name/sector/industry/market cap/price) via a
                  batched yfinance call. No EDGAR, no prices, no scoring. Used
                  to build the universe catalog so users can browse industries.

  Deep ingest   - the full Phase 2 pipeline (EDGAR financials + price history +
                  scores) for every company in a chosen industry.

The public functions here are also what the Flask routes and CLI call.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

# Allow running as a script from inside backend/
import sys as _sys
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in _sys.path:
    _sys.path.insert(0, _BACKEND)

from database import models
from ingestion import edgar
from ingestion import yfinance_fetcher as yfx

log = logging.getLogger(__name__)

# SEC file that (unlike company_tickers.json) carries the listing exchange.
_TICKER_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
_TICKER_EXCHANGE_PATH = os.path.join(edgar.CACHE_DIR, "company_tickers_exchange.json")
_TICKER_EXCHANGE_TTL = 7 * 24 * 3600  # weekly

# Exchanges we keep. The SEC file uses these short codes.
_MAJOR_EXCHANGES = {"Nasdaq", "NYSE", "NYSE American", "NYSE Arca", "CboeBZX", "BATS", "AMEX"}

LIGHT_FRESH_DAYS = 30  # skip re-light-ingesting a profile updated within this window


# ----------------------------- industry name normalization -----------------------------

def normalize_industry(name: Optional[str]) -> Optional[str]:
    """Normalize an industry label for consistent grouping.

    yfinance is inconsistent about dash style and whitespace
    ("Banks-Regional" vs "Banks - Regional" vs "Banks—Regional").
    We collapse all dash variants to " - " with single spaces, and trim.
    The result is the *stored/display* form; comparison elsewhere is exact
    against this normalized value.
    """
    if not name:
        return name
    s = str(name).strip()
    # Unify unicode dashes to ascii hyphen
    for dash in ("—", "–", "−"):
        s = s.replace(dash, "-")
    # Collapse "A-B", "A -B", "A- B", "A - B" all to "A - B"
    parts = [p.strip() for p in s.split("-")]
    s = " - ".join(p for p in parts if p != "")
    # Collapse any runs of whitespace
    s = " ".join(s.split())
    return s or None


# ----------------------------- ticker universe -----------------------------

def _load_exchange_map(force_refresh: bool = False) -> dict[str, dict]:
    """Return ticker (uppercase) -> {"cik", "name", "exchange"} from the SEC
    company_tickers_exchange.json file. Cached weekly on disk.
    """
    os.makedirs(edgar.CACHE_DIR, exist_ok=True)
    fresh = (
        os.path.exists(_TICKER_EXCHANGE_PATH)
        and not force_refresh
        and (time.time() - os.path.getmtime(_TICKER_EXCHANGE_PATH)) < _TICKER_EXCHANGE_TTL
    )
    if not fresh:
        log.info("Refreshing SEC ticker+exchange map from %s", _TICKER_EXCHANGE_URL)
        resp = edgar._rate_limited_get(_TICKER_EXCHANGE_URL, host="www.sec.gov")
        with open(_TICKER_EXCHANGE_PATH, "w", encoding="utf-8") as f:
            f.write(resp.text)

    with open(_TICKER_EXCHANGE_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # File format: {"fields": ["cik","name","ticker","exchange"], "data": [[...], ...]}
    fields = raw.get("fields", [])
    try:
        i_cik = fields.index("cik")
        i_name = fields.index("name")
        i_ticker = fields.index("ticker")
        i_exch = fields.index("exchange")
    except ValueError:
        log.error("Unexpected company_tickers_exchange.json layout: %s", fields)
        return {}

    out: dict[str, dict] = {}
    for row in raw.get("data", []):
        ticker = str(row[i_ticker] or "").upper()
        if not ticker:
            continue
        out[ticker] = {
            "cik": str(row[i_cik]).zfill(10),
            "name": row[i_name] or "",
            "exchange": row[i_exch] or "",
        }
    return out


# Order exchanges roughly by how many major names they carry, so that a
# capped/sampled slice still spans the biggest venues first.
_EXCHANGE_RANK = {"NYSE": 0, "Nasdaq": 1, "NYSE American": 2, "AMEX": 2,
                  "NYSE Arca": 3, "CboeBZX": 4, "BATS": 4}


def get_all_tickers() -> list[dict]:
    """All US-listed tickers on major exchanges (NYSE/NASDAQ/AMEX family).

    Returns [{"cik", "ticker", "name", "exchange"}], filtering out OTC,
    foreign, and unlisted entries (exchange blank or not in the major set).

    Sorted by exchange rank then ticker (NOT by company name). The raw SEC
    file is ordered alphabetically by company name, which — when a caller
    takes the first N — biases toward A-C names and a handful of industries.
    Sorting by ticker instead gives a diverse spread across the alphabet and
    across industries for any prefix of the list.
    """
    emap = _load_exchange_map()
    out: list[dict] = []
    for ticker, info in emap.items():
        exch = info.get("exchange") or ""
        if exch not in _MAJOR_EXCHANGES:
            continue
        # yfinance uses '-' for share classes (BRK.B -> BRK-B)
        yf_ticker = ticker.replace(".", "-")
        out.append({
            "cik": info["cik"],
            "ticker": yf_ticker,
            "name": info["name"],
            "exchange": exch,
        })
    out.sort(key=lambda t: (_EXCHANGE_RANK.get(t["exchange"], 9), t["ticker"]))
    return out


# ----------------------------- light ingest -----------------------------

def _batch_fetch_profiles(symbols: list[str]) -> dict[str, dict]:
    """Fetch profiles for a batch of tickers via yf.Tickers(...).

    Returns {symbol: profile_dict}. Missing/invalid tickers are omitted.
    Falls back to per-ticker fetch_profile on batch failure.
    """
    import math
    import yfinance as yf

    joined = " ".join(symbols)
    out: dict[str, dict] = {}
    try:
        batch = yf.Tickers(joined)
    except Exception as e:
        log.warning("yf.Tickers batch failed (%s); falling back per-ticker", e)
        for s in symbols:
            p = yfx.fetch_profile(s)
            if p:
                out[s.upper()] = p
        return out

    for s in symbols:
        try:
            info = batch.tickers[s].info or {}
        except Exception as e:
            log.debug("[%s] batch info fetch failed: %s", s, e)
            continue
        if not info:
            continue
        name = info.get("longName") or info.get("shortName")
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        # Skip tickers yfinance has nothing useful for
        if not name and price is None:
            continue

        def _clean(v):
            if isinstance(v, float) and math.isnan(v):
                return None
            return v

        out[s.upper()] = {
            "name": name,
            "sector": info.get("sector"),
            "industry": normalize_industry(info.get("industry")),
            "market_cap": _clean(info.get("marketCap")),
            "price": _clean(price),
            "shares_outstanding": _clean(info.get("sharesOutstanding")),
            "exchange": info.get("exchange"),
        }
    return out


def light_ingest_batch(symbols: list[str], batch_size: int = 50) -> int:
    """Profile-only ingestion for many tickers, batched for speed.

    Skips tickers whose profile was updated within the last 30 days. Returns
    the count of companies successfully upserted this run.
    """
    from ingestion.bulk_ingest import _is_fresh

    syms = [s.upper() for s in symbols]
    ingested = 0
    fresh_skipped = 0
    unreachable = 0
    total = len(syms)

    for start in range(0, total, batch_size):
        chunk = syms[start:start + batch_size]

        # Skip ones that are already fresh
        to_fetch = []
        for s in chunk:
            existing = models.get_company(s)
            if existing and _is_fresh(existing.get("last_profile_update"), LIGHT_FRESH_DAYS):
                fresh_skipped += 1
                continue
            to_fetch.append(s)

        if not to_fetch:
            log.info("light-ingest %d-%d: all fresh, skipping", start, start + len(chunk))
            continue

        log.info("light-ingest %d-%d: fetching %d profiles", start, start + len(chunk), len(to_fetch))
        profiles = _batch_fetch_profiles(to_fetch)
        # Tickers yfinance returned nothing useful for (delisted, no info, etc.)
        unreachable += len(to_fetch) - len(profiles)
        for sym, prof in profiles.items():
            # Attach CIK if the SEC map knows it (cheap local lookup)
            try:
                cik = edgar.get_cik(sym)
                if cik:
                    prof["cik"] = cik
            except Exception:
                pass
            models.upsert_company(sym, **prof)
            ingested += 1

        # Be polite to yfinance between batches
        time.sleep(1.0)

    log.info(
        "light_ingest_batch: %d ingested, %d already-fresh, %d unreachable "
        "(no yfinance data) of %d requested",
        ingested, fresh_skipped, unreachable, total,
    )
    return ingested


# ----------------------------- industry queries -----------------------------

def get_available_industries(min_count: int = 5) -> list[dict]:
    """Distinct industries in the local DB with company counts (count >= min_count),
    most-populous first. Thin wrapper over models.get_industries."""
    return models.get_industries(min_count=min_count)


def get_companies_in_industry(industry: str) -> list[dict]:
    """All local companies matching an (already-normalized) industry name."""
    return models.get_companies_by_industry(normalize_industry(industry))


# ----------------------------- deep ingest -----------------------------

def deep_ingest_industry(industry: str, limit: Optional[int] = None) -> dict:
    """Run the full Phase 2 pipeline for every company in an industry.

    Companies already deep-ingested within the last 90 days (fresh financials
    AND fresh profile) are skipped. Returns a summary dict.
    """
    from ingestion.bulk_ingest import ingest_company, _is_fresh, FRESH_DAYS

    norm = normalize_industry(industry)
    companies = models.get_companies_by_industry(norm, limit=limit)
    total = len(companies)
    summary = {
        "industry": norm,
        "total": total,
        "ingested": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
    }

    for i, comp in enumerate(companies, 1):
        sym = comp["symbol"]

        # Skip if already deep-ingested recently: has financials + fresh profile.
        # (comp from get_companies_by_industry omits last_profile_update, so read
        # the full company row for the freshness check.)
        existing_fin = models.get_financials(sym, limit=1)
        full = models.get_company(sym) or {}
        if existing_fin and _is_fresh(full.get("last_profile_update"), FRESH_DAYS):
            # Fresh, but companies deep-ingested before Phase 3 may lack
            # historical valuations. Recompute scores (no API calls) so IV
            # trends + model-accuracy inputs get backfilled before we skip.
            if not models.get_historical_valuations(sym):
                log.info("[%d/%d] %s: fresh but no IV history, recomputing scores", i, total, sym)
                try:
                    from ingestion.bulk_ingest import compute_and_store_scores
                    compute_and_store_scores(sym)
                except Exception:
                    log.exception("[%s] score backfill failed", sym)
            else:
                log.info("[%d/%d] %s: fresh deep ingest, skipping", i, total, sym)
            summary["skipped"] += 1
            continue

        log.info("[%d/%d] %s: deep ingesting...", i, total, sym)
        try:
            status = ingest_company(sym)
            if status["ok"]:
                summary["ingested"] += 1
            else:
                summary["failed"] += 1
                summary["errors"].append({"symbol": sym, "errors": status["errors"]})
        except Exception as e:
            log.exception("[%s] deep ingest crashed", sym)
            summary["failed"] += 1
            summary["errors"].append({"symbol": sym, "errors": [str(e)]})

    log.info(
        "deep_ingest_industry(%s): %d ingested, %d skipped, %d failed",
        norm, summary["ingested"], summary["skipped"], summary["failed"],
    )
    return summary
