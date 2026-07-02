"""Bulk ingestion orchestrator.

Per-company flow:
  1. Fetch yfinance profile -> upsert into companies (with CIK from EDGAR map)
  2. Fetch EDGAR companyfacts -> parse annual financials -> upsert
  3. Fetch yfinance daily prices -> upsert
  4. Run Graham + Fisher + valuation models -> upsert into scores

CLI usage (run from backend/):
  py -m ingestion.bulk_ingest --symbols AAPL,KO,JNJ
  py -m ingestion.bulk_ingest --universe sp500
  py -m ingestion.bulk_ingest --refresh-prices
  py -m ingestion.bulk_ingest --refresh-scores
  py -m ingestion.bulk_ingest --discover-universe            # light-ingest ~3000 tickers
  py -m ingestion.bulk_ingest --discover-universe --sample 100   # test on a subset
  py -m ingestion.bulk_ingest --industry "Banks - Regional"
  py -m ingestion.bulk_ingest --industry "Banks - Regional" --limit 100
  py -m ingestion.bulk_ingest --industry "Banks - Regional" --compute-accuracy
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
import time
from typing import Iterable, Optional

# Allow running as a script from inside backend/
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_BACKEND = _os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from analysis.graham import score_graham
from analysis.fisher import score_fisher
from analysis.valuation import compute_valuations
from database import models
from ingestion import edgar
from ingestion import yfinance_fetcher as yfx
from ingestion.db_adapter import to_analysis_inputs

log = logging.getLogger(__name__)

PRICE_HISTORY_START = "2010-01-01"
FRESH_DAYS = 90  # consider data fresh if updated within this window
# Cap for --discover-universe light ingest. Set high enough (8000) that the
# ~7600-ticker major-exchange list passes through in full; the exchange filter
# in get_all_tickers() is the real limiter. Use --sample N to test on a subset.
DISCOVER_DEFAULT_MAX = 8000


# ----------------------------- universe lists -----------------------------

def get_starter_tickers() -> list[str]:
    """A small hand-picked starter set spanning sectors. Useful for testing
    end-to-end without committing to a full S&P 500 ingest."""
    return [
        "AAPL", "MSFT", "GOOGL", "AMZN", "META",       # Tech
        "KO", "PEP", "PG", "WMT", "COST",              # Consumer Defensive
        "JNJ", "PFE", "MRK", "ABBV", "LLY",            # Healthcare
        "JPM", "BAC", "WFC", "GS", "MS",               # Financials
        "XOM", "CVX",                                   # Energy
        "BRK-B", "V", "MA",                             # Diversified
    ]


def get_sp500_tickers() -> list[str]:
    """Scrape the current S&P 500 constituents from Wikipedia.

    Falls back to the starter list if scraping fails (e.g. no network).
    Wikipedia changes table structure occasionally; if that breaks, the
    user can pass --symbols explicitly.
    """
    try:
        import requests
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        resp = requests.get(url, headers={"User-Agent": "ValueInvestor"}, timeout=20)
        resp.raise_for_status()
        # Light HTML parse — avoid pulling in pandas just for this.
        import re
        m = re.search(r'id="constituents".*?</table>', resp.text, re.DOTALL)
        if not m:
            raise RuntimeError("could not locate constituents table")
        rows = re.findall(r'<tr>(.*?)</tr>', m.group(0), re.DOTALL)
        tickers: list[str] = []
        for row in rows:
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            if not cells:
                continue
            # First cell contains the ticker symbol (sometimes wrapped in <a>)
            cell = re.sub(r'<[^>]+>', '', cells[0]).strip()
            if cell and len(cell) <= 6 and cell.replace(".", "").replace("-", "").isalnum():
                tickers.append(cell.replace(".", "-"))  # BRK.B -> BRK-B for yfinance
        if len(tickers) < 400:
            raise RuntimeError(f"scraped only {len(tickers)} tickers — table format may have changed")
        return tickers
    except Exception as e:
        log.warning("S&P 500 scrape failed (%s); falling back to starter list", e)
        return get_starter_tickers()


# ----------------------------- per-company ingest -----------------------------

def _is_fresh(iso_ts: Optional[str], window_days: int = FRESH_DAYS) -> bool:
    if not iso_ts:
        return False
    try:
        ts = dt.datetime.fromisoformat(iso_ts)
    except ValueError:
        return False
    return (dt.datetime.utcnow() - ts) < dt.timedelta(days=window_days)


def ingest_company(symbol: str, fetch_prices: bool = True, fetch_financials: bool = True) -> dict:
    """Full ingestion for one ticker. Returns a status dict.

    fetch_financials=False skips the EDGAR call (used by --refresh-prices).
    fetch_prices=False skips price history (used by --refresh-scores rebuild).
    """
    sym = symbol.upper()
    status = {"symbol": sym, "ok": True, "errors": [], "stages": {}}

    # ---- 1. profile via yfinance ----
    try:
        prof = yfx.fetch_profile(sym)
        if prof is None:
            status["ok"] = False
            status["errors"].append("yfinance returned no profile")
        else:
            cik = edgar.get_cik(sym)
            if cik:
                prof["cik"] = cik
            prof.pop("symbol", None)  # upsert_company sets symbol from positional arg
            models.upsert_company(sym, **prof)
            status["stages"]["profile"] = "ok"
    except Exception as e:
        status["ok"] = False
        status["errors"].append(f"profile: {e}")
        log.exception("[%s] profile fetch failed", sym)

    # ---- 2. financials via EDGAR ----
    fin_count = 0
    if fetch_financials:
        try:
            cik = edgar.get_cik(sym)
            if not cik:
                status["errors"].append("no CIK for ticker (not in SEC ticker map)")
                status["stages"]["financials"] = "skipped (no CIK)"
            else:
                facts = edgar.fetch_company_facts(cik)
                records = edgar.parse_annual_financials(facts, sym)
                for rec in records:
                    fy = rec.pop("fiscal_year")
                    rec.pop("symbol", None)  # upsert_financials sets it
                    models.upsert_financials(sym, fy, **rec)
                fin_count = len(records)
                status["stages"]["financials"] = f"ok ({fin_count} years)"
        except Exception as e:
            status["errors"].append(f"financials: {e}")
            log.exception("[%s] EDGAR fetch/parse failed", sym)

    # ---- 3. prices via yfinance ----
    if fetch_prices:
        try:
            existing = models.get_daily_prices(sym)
            if existing:
                last = max(r["date"] for r in existing)
                start = (dt.date.fromisoformat(last) + dt.timedelta(days=1)).isoformat()
            else:
                start = PRICE_HISTORY_START
            today = dt.date.today().isoformat()
            if start <= today:
                rows = yfx.fetch_daily_prices(sym, start=start)
                n = models.upsert_daily_prices(sym, rows)
                status["stages"]["prices"] = f"ok ({n} bars)"
            else:
                status["stages"]["prices"] = "ok (already current)"
        except Exception as e:
            status["errors"].append(f"prices: {e}")
            log.exception("[%s] yfinance price fetch failed", sym)

    # ---- 4. scores ----
    try:
        compute_and_store_scores(sym)
        status["stages"]["scores"] = "ok"
    except Exception as e:
        status["errors"].append(f"scores: {e}")
        log.exception("[%s] scoring failed", sym)

    if status["errors"]:
        status["ok"] = False
    return status


# ----------------------------- scoring -----------------------------

def compute_and_store_scores(symbol: str) -> Optional[dict]:
    """Run Graham + Fisher + valuation against DB data; persist to scores."""
    sym = symbol.upper()
    company = models.get_company(sym)
    if not company:
        log.warning("[%s] no company row, skipping scoring", sym)
        return None
    financials = models.get_financials(sym, limit=20)
    if not financials:
        log.warning("[%s] no financials, skipping scoring", sym)
        return None

    inputs = to_analysis_inputs(company, financials)

    graham = score_graham(
        inputs["profile"], inputs["income"], inputs["balance"],
        inputs["cashflow"], inputs["key_metrics"],
    )
    fisher = score_fisher(
        inputs["profile"], inputs["income"], inputs["balance"], inputs["cashflow"],
    )
    valuation = compute_valuations(
        inputs["profile"], inputs["income"], inputs["balance"], inputs["cashflow"],
    )

    models_dict = valuation.get("models", {}) or {}
    composite = valuation.get("compositeValue")
    price = company.get("price")
    discount = None
    if composite and price and price > 0:
        discount = (composite - price) / composite

    # ---- historical intrinsic-value trends (Phase 3) ----
    iv_metrics = _compute_and_store_iv_trends(sym, company, financials)

    score_payload = {
        "graham_total": graham.get("totalScore"),
        "graham_max": graham.get("maxScore"),
        "graham_pct": graham.get("pctScore"),
        "graham_grade": graham.get("grade"),
        "graham_details": json.dumps({
            "scores": graham.get("scores"),
            "details": graham.get("details"),
        }),
        "fisher_total": fisher.get("totalScore"),
        "fisher_max": fisher.get("maxScore"),
        "fisher_pct": fisher.get("pctScore"),
        "fisher_grade": fisher.get("grade"),
        "fisher_details": json.dumps({
            "scores": fisher.get("scores"),
            "details": fisher.get("details"),
        }),
        "intrinsic_value_graham": _model_iv(models_dict, "graham"),
        "intrinsic_value_dcf": _model_iv(models_dict, "dcf"),
        "intrinsic_value_book": _model_iv(models_dict, "bookValue"),
        "intrinsic_value_epv": _model_iv(models_dict, "epv"),
        "intrinsic_value_ncav": _model_iv(models_dict, "ncav"),
        "intrinsic_value_composite": composite,
        "discount_to_intrinsic": discount,
        "signal": valuation.get("signal"),
        "iv_cagr_5yr": iv_metrics.get("cagr_5yr"),
        "iv_cagr_10yr": iv_metrics.get("cagr_10yr"),
        "iv_trend": iv_metrics.get("trend"),
        "iv_stability": iv_metrics.get("stability"),
    }
    models.upsert_scores(sym, **score_payload)
    return score_payload


def _compute_and_store_iv_trends(symbol: str, company: dict, financials: list[dict]) -> dict:
    """Compute historical valuations, persist them, and return IV growth
    metrics for the scores row. Non-fatal: logs and returns empties on error.
    """
    from analysis import iv_trends
    empty = {"cagr_5yr": None, "cagr_10yr": None, "trend": None, "stability": None}
    try:
        prices = models.get_daily_prices(symbol)
        history = iv_trends.compute_historical_valuations(
            symbol, financials, company, daily_prices=prices
        )
        for yr in history:
            for model_name, m in yr["models"].items():
                models.upsert_historical_valuation(
                    symbol, yr["fiscal_year"], model_name,
                    m.get("intrinsic_value"), m.get("inputs"),
                )
        metrics = iv_trends.compute_iv_growth_rate(history)
        return metrics
    except Exception:
        log.exception("[%s] IV trend computation failed", symbol)
        return empty


def _model_iv(models_dict: dict, key: str):
    m = models_dict.get(key)
    if not m:
        return None
    return m.get("intrinsicValue")


# ----------------------------- bulk drivers -----------------------------

def bulk_ingest(
    symbols: Iterable[str],
    skip_existing: bool = True,
    sleep_between: float = 0.5,
) -> list[dict]:
    """Ingest a list of tickers. Skips ones whose profile is fresh.

    Logs progress and continues past per-symbol errors.
    """
    syms = [s.upper() for s in symbols]
    results: list[dict] = []
    total = len(syms)

    for i, sym in enumerate(syms, 1):
        existing = models.get_company(sym)
        if skip_existing and existing and _is_fresh(existing.get("last_profile_update")):
            log.info("[%d/%d] %s: fresh, skipping", i, total, sym)
            results.append({"symbol": sym, "ok": True, "skipped": True})
            continue

        log.info("[%d/%d] %s: ingesting...", i, total, sym)
        t0 = time.monotonic()
        status = ingest_company(sym)
        elapsed = time.monotonic() - t0
        if status["ok"]:
            log.info("[%d/%d] %s: done in %.1fs (%s)", i, total, sym, elapsed, status["stages"])
        else:
            log.error("[%d/%d] %s: errors: %s", i, total, sym, status["errors"])
        results.append(status)

        if sleep_between and i < total:
            time.sleep(sleep_between)

    return results


def refresh_prices(symbols: Optional[list[str]] = None, sleep_between: float = 0.5) -> int:
    """Update prices for the given symbols (or all DB companies).

    Bulk-fetches in chunks of 50 for speed. Returns total rows written.
    """
    from database.db import get_db
    if symbols is None:
        rows = get_db().execute("SELECT symbol FROM companies ORDER BY symbol").fetchall()
        symbols = [r["symbol"] for r in rows]
    if not symbols:
        return 0

    today = dt.date.today().isoformat()
    total_written = 0

    for i in range(0, len(symbols), 50):
        chunk = symbols[i:i + 50]
        # Determine the earliest "since" across this chunk
        since = PRICE_HISTORY_START
        chunk_starts: dict[str, str] = {}
        for s in chunk:
            existing = models.get_daily_prices(s)
            if existing:
                last = max(r["date"] for r in existing)
                chunk_starts[s] = (dt.date.fromisoformat(last) + dt.timedelta(days=1)).isoformat()
            else:
                chunk_starts[s] = PRICE_HISTORY_START
        # Use the earliest needed start for the bulk download
        since = min(chunk_starts.values())
        if since > today:
            log.info("chunk %d-%d: already current", i, i + len(chunk))
            continue

        log.info("chunk %d-%d: fetching prices since %s", i, i + len(chunk), since)
        bulk = yfx.fetch_daily_prices_bulk(chunk, start=since, end=today)
        for sym, rows_for_sym in bulk.items():
            sym_start = chunk_starts.get(sym, PRICE_HISTORY_START)
            filtered = [r for r in rows_for_sym if r["date"] >= sym_start]
            if filtered:
                total_written += models.upsert_daily_prices(sym, filtered)
        time.sleep(sleep_between)

    log.info("refresh_prices wrote %d rows across %d symbols", total_written, len(symbols))
    return total_written


def discover_universe(max_tickers: int = DISCOVER_DEFAULT_MAX, sample: Optional[int] = None) -> int:
    """Light-ingest profiles for the US-listed universe to build the catalog.

    Loads the SEC ticker+exchange list, filters to major exchanges, then
    profile-only ingests up to `max_tickers`. `sample` (if given) overrides
    the cap with a small N for testing.

    Returns the count of companies light-ingested.
    """
    from ingestion import industry_discovery as disc

    universe = disc.get_all_tickers()
    log.info("universe: %d US-listed tickers on major exchanges", len(universe))

    symbols = [u["ticker"] for u in universe]
    if sample is not None and len(symbols) > sample:
        # Stride evenly across the ticker-sorted universe so a small sample
        # spans the whole alphabet (and thus many industries) rather than
        # just the A-names at the front.
        step = len(symbols) / sample
        symbols = [symbols[int(i * step)] for i in range(sample)]
        log.info("sampling %d tickers strided across the universe", sample)
    elif len(symbols) > max_tickers:
        symbols = symbols[:max_tickers]
        log.info("capping to first %d tickers", max_tickers)
    else:
        log.info("no cap — light-ingesting all %d tickers", len(symbols))

    return disc.light_ingest_batch(symbols)


def deep_ingest_industry(industry: str, limit: Optional[int] = None,
                         compute_accuracy: bool = True) -> dict:
    """Deep-ingest an industry, then compute per-industry model accuracy."""
    from ingestion import industry_discovery as disc

    summary = disc.deep_ingest_industry(industry, limit=limit)

    if compute_accuracy:
        try:
            acc = compute_industry_accuracy(summary["industry"])
            summary["accuracy"] = {
                "best_model_3yr": acc.get("best_model_3yr"),
                "contributing_companies": acc.get("contributing_companies"),
            }
        except Exception:
            log.exception("[%s] model-accuracy computation failed", summary["industry"])

    return summary


def compute_industry_accuracy(industry: str) -> dict:
    """Compute and persist per-industry model accuracy. No API calls."""
    from analysis import model_accuracy
    from ingestion.industry_discovery import normalize_industry

    result = model_accuracy.store_industry_model_accuracy(normalize_industry(industry))
    log.info("model accuracy for %s: best=%s (from %d companies)",
             result["industry"], result["best_model_3yr"],
             result["contributing_companies"])
    return result


def refresh_scores(symbols: Optional[list[str]] = None) -> int:
    """Recompute scores for all (or specified) companies. No API calls."""
    from database.db import get_db
    if symbols is None:
        rows = get_db().execute("SELECT symbol FROM companies ORDER BY symbol").fetchall()
        symbols = [r["symbol"] for r in rows]
    n = 0
    for sym in symbols:
        try:
            if compute_and_store_scores(sym):
                n += 1
        except Exception:
            log.exception("[%s] score refresh failed", sym)
    log.info("refresh_scores rebuilt %d / %d", n, len(symbols))
    return n


# ----------------------------- CLI -----------------------------

def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bulk-ingest companies into the value-investor DB")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--symbols", help="comma-separated tickers, e.g. AAPL,KO,JNJ")
    g.add_argument("--universe", choices=["starter", "sp500"], help="preset universe")
    g.add_argument("--refresh-prices", action="store_true", help="update prices for all DB companies")
    g.add_argument("--refresh-scores", action="store_true", help="recompute scores from existing DB data")
    g.add_argument("--discover-universe", action="store_true",
                   help="light-ingest profiles for the US-listed universe (~3000 tickers)")
    g.add_argument("--industry", help="deep-ingest all companies in this industry")
    p.add_argument("--compute-accuracy", action="store_true",
                   help="with --industry: only (re)compute model accuracy, skip ingest")
    p.add_argument("--limit", type=int, default=None,
                   help="for --industry: only deep-ingest the top N by market cap")
    p.add_argument("--sample", type=int, default=None,
                   help="for --discover-universe: only process the first N tickers (testing)")
    p.add_argument("--no-skip-existing", action="store_true", help="re-ingest even if data is fresh")
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.refresh_prices:
        refresh_prices()
        return 0
    if args.refresh_scores:
        refresh_scores()
        return 0
    if args.discover_universe:
        n = discover_universe(sample=args.sample)
        print(f"\n=== discover-universe: light-ingested {n} companies ===")
        return 0
    if args.industry:
        if args.compute_accuracy:
            acc = compute_industry_accuracy(args.industry)
            print(f"\n=== model accuracy '{acc['industry']}' ===")
            print(f"  companies={acc['company_count']} "
                  f"contributing={acc['contributing_companies']} "
                  f"best_model_3yr={acc['best_model_3yr']}")
            for mdl, r in sorted(acc["model_rankings"].items(), key=lambda kv: kv[1]["rank"]):
                print(f"  #{r['rank']} {mdl:11} err3yr={r['avg_error_3yr']} "
                      f"weight={r['weight']} n={r['sample_size']}")
            return 0
        summary = deep_ingest_industry(args.industry, limit=args.limit)
        print(f"\n=== deep ingest '{summary['industry']}' ===")
        print(f"  total={summary['total']} ingested={summary['ingested']} "
              f"skipped={summary['skipped']} failed={summary['failed']}")
        if summary.get("accuracy"):
            print(f"  accuracy: best_model_3yr={summary['accuracy']['best_model_3yr']} "
                  f"(from {summary['accuracy']['contributing_companies']} companies)")
        for err in summary["errors"]:
            print(f"  {err['symbol']}: {'; '.join(err['errors'])}")
        return 0 if summary["failed"] == 0 else 1

    if args.symbols:
        syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    elif args.universe == "starter":
        syms = get_starter_tickers()
    elif args.universe == "sp500":
        syms = get_sp500_tickers()
    else:
        print("no symbols", file=sys.stderr)
        return 2

    results = bulk_ingest(syms, skip_existing=not args.no_skip_existing)

    ok = sum(1 for r in results if r.get("ok"))
    skipped = sum(1 for r in results if r.get("skipped"))
    print(f"\n=== ingestion summary: {ok}/{len(results)} ok ({skipped} skipped) ===")
    failures = [r for r in results if not r.get("ok") and not r.get("skipped")]
    for r in failures:
        print(f"  {r['symbol']}: {'; '.join(r['errors'])}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
