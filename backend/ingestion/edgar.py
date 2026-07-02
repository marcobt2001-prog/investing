"""SEC EDGAR XBRL data fetcher and parser.

EDGAR exposes every financial fact a company has ever filed via the
companyfacts endpoint. This module:

  1. Maintains a cached ticker -> CIK map (downloaded once from sec.gov).
  2. Fetches raw companyfacts JSON for a given CIK.
  3. Parses the raw facts into one normalized record per fiscal year,
     filtering for 10-K (annual) periods and applying the XBRL tag map.

SEC requires a User-Agent header with a contact email and asks clients
to stay under 10 requests/sec. We enforce both.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Optional

import requests

from .field_mapping import FIELD_PRIORITY, XBRL_TO_FIELD, tags_for_field

log = logging.getLogger(__name__)

USER_AGENT_NAME = "ValueInvestor"
USER_AGENT_EMAIL = "marcobt2001@gmail.com"
HEADERS = {
    "User-Agent": f"{USER_AGENT_NAME} {USER_AGENT_EMAIL}",
    "Accept": "application/json",
    "Host": "data.sec.gov",
}

# SEC asks for max 10 req/sec. We use 8/sec for a safety margin.
_MIN_INTERVAL = 1.0 / 8.0
_rate_lock = threading.Lock()
_last_request_at = 0.0

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cache")
_TICKER_MAP_PATH = os.path.join(CACHE_DIR, "ticker_to_cik.json")
_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_TICKER_MAP_TTL_SECONDS = 7 * 24 * 3600  # refresh weekly


# ----------------------------- HTTP plumbing -----------------------------

def _rate_limited_get(url: str, host: Optional[str] = None) -> requests.Response:
    """GET with global throttling and the SEC-required User-Agent."""
    global _last_request_at
    with _rate_lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()

    headers = dict(HEADERS)
    if host:
        headers["Host"] = host
    elif "data.sec.gov" not in url:
        # Default Host is data.sec.gov; correct it for www.sec.gov requests.
        headers["Host"] = "www.sec.gov"

    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp


# ----------------------------- CIK lookup -----------------------------

def _load_ticker_map(force_refresh: bool = False) -> dict[str, dict]:
    """Return ticker (uppercase) -> {"cik": str, "name": str} map.

    Cached on disk for one week. The bulk file from sec.gov is small (~1MB)
    and contains every public US ticker -> CIK mapping.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    fresh = (
        os.path.exists(_TICKER_MAP_PATH)
        and not force_refresh
        and (time.time() - os.path.getmtime(_TICKER_MAP_PATH)) < _TICKER_MAP_TTL_SECONDS
    )
    if not fresh:
        log.info("Refreshing SEC ticker->CIK map from %s", _TICKER_MAP_URL)
        resp = _rate_limited_get(_TICKER_MAP_URL, host="www.sec.gov")
        with open(_TICKER_MAP_PATH, "w", encoding="utf-8") as f:
            f.write(resp.text)

    with open(_TICKER_MAP_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # File format: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
    out: dict[str, dict] = {}
    for entry in raw.values():
        ticker = entry.get("ticker", "").upper()
        if not ticker:
            continue
        out[ticker] = {
            "cik": str(entry["cik_str"]).zfill(10),
            "name": entry.get("title", ""),
        }
    return out


def get_cik(ticker: str) -> Optional[str]:
    """Look up zero-padded 10-digit CIK for a ticker. None if not found."""
    tmap = _load_ticker_map()
    entry = tmap.get(ticker.upper())
    return entry["cik"] if entry else None


# ----------------------------- companyfacts fetch -----------------------------

def fetch_company_facts(cik: str) -> dict:
    """Fetch the full companyfacts JSON blob for a CIK (zero-padded)."""
    cik_padded = str(cik).zfill(10)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"
    resp = _rate_limited_get(url, host="data.sec.gov")
    return resp.json()


# ----------------------------- parsing -----------------------------

def _annual_units(unit_entries: list[dict]) -> list[dict]:
    """Filter unit observations down to annual 10-K data points.

    EDGAR observation fields:
      end:   period end date (e.g. "2024-09-28")  -- the real fiscal period
      start: period start date (income/cf only)
      val:   value
      fp:    fiscal period (FY for annual, Q1/Q2/.. for quarterly)
      form:  filing form (10-K, 10-Q, etc.)
      fy:    fiscal year *of the FILING* (NOT of the data point — every 10-K
             carries 2-3 years of comparatives, all tagged with the report's fy)
      filed: filing date

    For annual data we want form == "10-K" AND a ~365-day start..end span.
    Balance-sheet facts have only `end`, so keep those too.
    """
    annual: list[dict] = []
    for obs in unit_entries:
        form = obs.get("form", "")
        if form not in ("10-K", "10-K/A"):
            continue

        # Income / cash-flow facts have a start..end span. Require ~365 days
        # to drop quarterly amounts that show up in 10-K filings.
        start = obs.get("start")
        end = obs.get("end")
        if not end:
            continue
        if start:
            try:
                from datetime import date
                s = date.fromisoformat(start)
                e = date.fromisoformat(end)
                span_days = (e - s).days
                if span_days < 350 or span_days > 380:
                    continue
            except ValueError:
                continue
        # Balance-sheet facts have only `end` (point in time). Keep them.

        annual.append(obs)
    return annual


def _pick_for_year(observations: list[dict], fy: int) -> Optional[dict]:
    """Pick the observation that represents fiscal year `fy`.

    The crucial bit: an observation's *fiscal year* is determined by its
    `end` date, NOT by the `fy` field on the obs (which is the filing's fy
    and includes 2-3 years of prior-period comparatives).

    For each distinct `end` date, prefer the most-recently-filed value
    (handles restatements). Then return the one whose end date best
    matches the requested fiscal year, scoring (end.year, end.month).
    Companies with non-Sept fiscal years still match: Apple FY 2024 ends
    in Sept 2024 (end.year == 2024); Walmart FY 2024 ends in Jan 2025
    (end.year == 2025), so we accept end.year in {fy, fy+1}.
    """
    if not observations:
        return None

    # Pick the most-recently-filed obs for each distinct period end.
    by_end: dict[str, dict] = {}
    for obs in observations:
        end = obs.get("end")
        if not end:
            continue
        prev = by_end.get(end)
        if prev is None or obs.get("filed", "") > prev.get("filed", ""):
            by_end[end] = obs

    # Find the obs whose fiscal year matches.
    from datetime import date
    candidates: list[tuple[int, dict]] = []  # (priority, obs)
    for end_str, obs in by_end.items():
        try:
            end_date = date.fromisoformat(end_str)
        except ValueError:
            continue
        # Apple-style (Sept FY-end): end.year == fy
        # Walmart-style (Jan FY-end, fiscal calendar leads): end.year == fy or fy+1
        if end_date.year == fy:
            candidates.append((0, obs))
        elif end_date.year == fy + 1 and end_date.month <= 6:
            # Fiscal year ending in early calendar year (Jan-June) maps to prior fy
            candidates.append((1, obs))

    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], -int(x[1].get("filed", "0000-00-00").replace("-", ""))))
    return candidates[0][1]


def _extract_field(facts: dict, field: str, fy: int) -> tuple[Optional[float], Optional[str]]:
    """Try every XBRL tag mapped to `field` (in priority order) for the given
    fiscal year. Returns (value, tag_used) or (None, None)."""
    us_gaap = facts.get("facts", {}).get("us-gaap", {})

    for tag in tags_for_field(field):
        if tag not in us_gaap:
            continue
        units = us_gaap[tag].get("units", {})
        # Prefer USD; fall back to USD/shares for per-share fields, or
        # plain "shares" for share counts, or whatever's first otherwise.
        unit_keys = list(units.keys())
        preferred_unit = None
        for u in ("USD", "USD/shares", "shares"):
            if u in unit_keys:
                preferred_unit = u
                break
        if preferred_unit is None and unit_keys:
            preferred_unit = unit_keys[0]
        if preferred_unit is None:
            continue

        annual = _annual_units(units[preferred_unit])
        obs = _pick_for_year(annual, fy)
        if obs is not None and obs.get("val") is not None:
            return float(obs["val"]), tag
    return None, None


def _all_fiscal_years(facts: dict) -> list[int]:
    """Distinct fiscal years for which the company has annual 10-K data.

    We derive the fiscal year from each observation's `end` date rather
    than the `fy` field (which represents the report's fy, not the data
    point's). Probe a handful of common income-statement / balance-sheet
    tags so we handle companies that switched revenue tags over time.
    """
    from datetime import date
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    probe_tags = (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "Assets",
        "NetIncomeLoss",
    )
    years: set[int] = set()
    for tag in probe_tags:
        tag_data = us_gaap.get(tag)
        if not tag_data:
            continue
        for unit_entries in tag_data.get("units", {}).values():
            for obs in _annual_units(unit_entries):
                end = obs.get("end")
                if not end:
                    continue
                try:
                    end_date = date.fromisoformat(end)
                except ValueError:
                    continue
                # Derive fy: assume calendar year of end date is the fy,
                # except when end is in Jan-June, which means fy = prior year
                # (Walmart-style fiscal calendars).
                fy = end_date.year if end_date.month >= 7 else end_date.year - 1
                years.add(fy)
    return sorted(years, reverse=True)


def _safe_div(n: Optional[float], d: Optional[float]) -> Optional[float]:
    if n is None or d in (None, 0):
        return None
    try:
        return n / d
    except (TypeError, ZeroDivisionError):
        return None


def _compute_derived(rec: dict) -> None:
    """Fill in derived metrics on a record dict in place."""
    # Gross profit if not reported directly
    if rec.get("gross_profit") is None and rec.get("revenue") is not None and rec.get("cost_of_revenue") is not None:
        rec["gross_profit"] = rec["revenue"] - rec["cost_of_revenue"]

    # Total debt = long-term + current portion (if either present)
    lt = rec.pop("long_term_debt", None)
    st = rec.pop("short_term_debt", None)
    if lt is not None or st is not None:
        rec["total_debt"] = (lt or 0.0) + (st or 0.0)

    # Free cash flow: operating CF - |capex|
    if rec.get("operating_cash_flow") is not None and rec.get("capital_expenditure") is not None:
        rec["free_cash_flow"] = rec["operating_cash_flow"] - abs(rec["capital_expenditure"])

    # Ratios
    rec["current_ratio"] = _safe_div(rec.get("total_current_assets"), rec.get("total_current_liabilities"))
    rec["debt_to_equity"] = _safe_div(rec.get("total_debt"), rec.get("total_stockholders_equity"))
    rec["gross_margin"] = _safe_div(rec.get("gross_profit"), rec.get("revenue"))
    rec["operating_margin"] = _safe_div(rec.get("operating_income"), rec.get("revenue"))
    rec["net_margin"] = _safe_div(rec.get("net_income"), rec.get("revenue"))
    rec["roe"] = _safe_div(rec.get("net_income"), rec.get("total_stockholders_equity"))
    rec["roa"] = _safe_div(rec.get("net_income"), rec.get("total_assets"))
    rec["fcf_margin"] = _safe_div(rec.get("free_cash_flow"), rec.get("revenue"))


# Fields we extract directly from XBRL (excludes derived ratios + total_debt)
_EXTRACT_FIELDS = [
    "revenue", "cost_of_revenue", "gross_profit", "operating_income",
    "net_income", "eps", "eps_diluted",
    "research_and_development", "sga_expense",
    "weighted_avg_shares", "weighted_avg_shares_diluted",
    "total_assets", "total_current_assets",
    "total_liabilities", "total_current_liabilities",
    "long_term_debt", "short_term_debt",
    "total_stockholders_equity", "retained_earnings", "cash_and_equivalents",
    "operating_cash_flow", "capital_expenditure", "dividends_paid",
]


def parse_annual_financials(facts: dict, ticker: str) -> list[dict]:
    """Convert raw EDGAR companyfacts JSON into one record per fiscal year.

    Each returned dict has the normalized field names matching the
    `financials` SQLite table (minus `fetched_at`, which the DB layer fills).
    Records with no revenue AND no net income are skipped — those years
    likely predate the company's first 10-K.
    """
    years = _all_fiscal_years(facts)
    if not years:
        log.warning("[%s] no 10-K fiscal years found in companyfacts", ticker)
        return []

    # Capture fiscal_date (period end) using whatever field showed up — try
    # revenue / total_assets / net_income tags in turn.
    us_gaap = facts.get("facts", {}).get("us-gaap", {})

    out: list[dict] = []
    unmapped_warned: set[str] = set()

    for fy in years:
        rec: dict[str, Any] = {
            "symbol": ticker.upper(),
            "fiscal_year": fy,
            "source": "edgar",
        }

        # Pull each field
        for field in _EXTRACT_FIELDS:
            val, tag = _extract_field(facts, field, fy)
            if val is not None:
                rec[field] = val

        # Determine fiscal_date from the most informative observation we can find.
        for probe_tag in ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "Assets", "NetIncomeLoss"):
            tag_obj = us_gaap.get(probe_tag)
            if not tag_obj:
                continue
            units = tag_obj.get("units", {})
            usd = units.get("USD") or next(iter(units.values()), [])
            obs = _pick_for_year(_annual_units(usd), fy)
            if obs and obs.get("end"):
                rec["fiscal_date"] = obs["end"]
                break

        # Skip empty years
        if rec.get("revenue") is None and rec.get("net_income") is None and rec.get("total_assets") is None:
            continue

        _compute_derived(rec)
        out.append(rec)

    # Log a one-shot warning if any obviously-expected fields never appeared.
    if out:
        latest = out[0]
        for f in ("revenue", "net_income", "total_assets"):
            if latest.get(f) is None and f not in unmapped_warned:
                log.warning("[%s] no value for %s in latest fiscal year %s — XBRL tag not mapped",
                            ticker, f, latest.get("fiscal_year"))
                unmapped_warned.add(f)

    return out


# ----------------------------- public convenience -----------------------------

def fetch_annual_financials(ticker: str) -> list[dict]:
    """One-shot: ticker -> CIK -> companyfacts -> parsed annual records."""
    cik = get_cik(ticker)
    if cik is None:
        raise ValueError(f"No CIK found for ticker {ticker}")
    facts = fetch_company_facts(cik)
    return parse_annual_financials(facts, ticker)
