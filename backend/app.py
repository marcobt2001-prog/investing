"""Flask server for the Value Investor Intelligence System.

Phase 2: routes prefer the local SQLite database. FMP is kept as a
fallback for tickers that haven't been ingested yet (and only used when
the caller passes an apikey).
"""

from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import csv
import datetime as dt
import io
import json
import logging
import requests
import time

from analysis.graham import score_graham
from analysis.fisher import score_fisher
from analysis.valuation import compute_valuations
from analysis.backtest import run_backtest

from database import models
from database.db import get_db
from ingestion import bulk_ingest
from ingestion.db_adapter import to_analysis_inputs, historical_prices_fmp_shape

app = Flask(__name__)
CORS(app)

log = logging.getLogger(__name__)

FMP_BASE = "https://financialmodelingprep.com/stable"
FMP_STMT_LIMIT = "5"  # FMP free-tier cap

# Considered fresh enough to skip a fresh ingest when /api/analyze is called.
ANALYZE_FRESH_DAYS = 90

# Curated stock universe by sector — kept for the FMP-fallback /api/screen
# path and the frontend's sector dropdown. The DB-backed screener doesn't use it.
STOCK_UNIVERSE = {
    "Technology": ["AAPL", "MSFT", "GOOGL", "NVDA", "META", "AVGO", "ORCL", "CRM", "AMD", "INTC",
                   "ADBE", "CSCO", "TXN", "QCOM", "IBM", "NOW", "INTU", "AMAT", "MU", "LRCX"],
    "Healthcare": ["JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY", "TMO", "ABT", "DHR", "BMY",
                   "AMGN", "MDT", "GILD", "ISRG", "CVS", "ELV", "SYK", "ZTS", "VRTX", "BDX"],
    "Financial Services": ["JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW", "C", "AXP", "USB",
                           "PNC", "TFC", "BK", "CME", "ICE", "AON", "MMC", "CB", "MET", "AIG"],
    "Consumer Defensive": ["PG", "KO", "PEP", "WMT", "COST", "PM", "MO", "CL", "MDLZ", "GIS",
                           "KMB", "SYY", "K", "HSY", "TSN", "CAG", "CPB", "SJM", "KHC", "HRL"],
    "Consumer Cyclical": ["AMZN", "TSLA", "HD", "NKE", "MCD", "SBUX", "LOW", "TJX", "BKNG", "MAR",
                          "GM", "F", "LULU", "CMG", "YUM", "DPZ", "EBAY", "ETSY", "BBY", "DHI"],
    "Industrials": ["CAT", "HON", "UPS", "RTX", "BA", "GE", "DE", "LMT", "MMM", "UNP",
                    "WM", "ETN", "ITW", "EMR", "FDX", "NSC", "CSX", "GD", "NOC", "TT"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OXY", "PXD",
               "HES", "DVN", "HAL", "BKR", "FANG", "WMB", "KMI", "OKE", "TRGP", "LNG"],
    "Utilities": ["NEE", "DUK", "SO", "D", "AEP", "SRE", "EXC", "XEL", "ED", "WEC",
                  "ES", "AWK", "DTE", "PPL", "FE", "EIX", "AEE", "CMS", "CNP", "ATO"],
    "Real Estate": ["AMT", "PLD", "CCI", "EQIX", "PSA", "SPG", "O", "WELL", "DLR", "AVB",
                    "EQR", "VTR", "ARE", "MAA", "UDR", "ESS", "PEAK", "HST", "KIM", "REG"],
    "Basic Materials": ["LIN", "APD", "SHW", "ECL", "FCX", "NEM", "NUE", "DD", "DOW", "PPG",
                        "VMC", "MLM", "ALB", "CE", "EMN", "FMC", "CF", "MOS", "IFF", "RPM"],
    "Communication Services": ["GOOG", "DIS", "CMCSA", "NFLX", "T", "VZ", "TMUS", "CHTR", "EA", "ATVI",
                               "TTWO", "MTCH", "ZM", "SNAP", "PINS", "ROKU", "PARA", "WBD", "LYV", "OMC"],
}


def fmp_get(path, apikey, extra_params=None):
    """GET against FMP's stable API with retry on 429."""
    params = {"apikey": apikey}
    if extra_params:
        params.update(extra_params)
    for attempt in range(3):
        resp = requests.get(f"{FMP_BASE}{path}", params=params, timeout=30)
        if resp.status_code == 429:
            time.sleep(2 * (attempt + 1))
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()
    return resp.json()


def _is_fresh(iso_ts, days=ANALYZE_FRESH_DAYS):
    if not iso_ts:
        return False
    try:
        ts = dt.datetime.fromisoformat(iso_ts)
    except ValueError:
        return False
    return (dt.datetime.utcnow() - ts) < dt.timedelta(days=days)


def _maybe_loads(blob):
    if not blob:
        return None
    if isinstance(blob, (dict, list)):
        return blob
    try:
        return json.loads(blob)
    except (TypeError, ValueError):
        return blob


# ---------- Health ----------

@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


# ---------- DB stats ----------

@app.route("/api/db/stats")
def db_stats():
    return jsonify(models.db_stats())


# ---------- Search ----------

@app.route("/api/search")
def search():
    """Search the local DB first; fall back to FMP if apikey is supplied
    and DB returned nothing useful."""
    query = request.args.get("query", "").strip()
    if not query:
        return jsonify({"error": "query parameter is required"}), 400

    local_hits = models.search_companies(query, limit=20)
    if local_hits:
        # Map to the FMP-search shape the frontend already understands.
        return jsonify([
            {
                "symbol": r["symbol"],
                "name": r.get("name"),
                "exchange": r.get("exchange"),
                "exchangeFullName": r.get("exchange"),
                "currency": "USD",
            }
            for r in local_hits
        ])

    # Fallback to FMP if the user provided a key.
    apikey = request.args.get("apikey")
    if not apikey:
        return jsonify([])
    try:
        results = fmp_get("/search-name", apikey, {"query": query, "limit": "20"})
        filtered = [r for r in results if r.get("exchange") in {"NASDAQ", "NYSE", "AMEX"}
                    or r.get("exchangeFullName", "").startswith("NASDAQ")
                    or r.get("exchangeFullName", "").startswith("NYSE")
                    or r.get("exchangeFullName", "").startswith("New York")]
        return jsonify(filtered)
    except requests.exceptions.HTTPError as e:
        return jsonify({"error": f"FMP API error: {e.response.status_code}"}), e.response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------- Screener ----------

def _parse_screen_params():
    """Pull screener filters from request.args. Returns kwargs for
    models.screen_companies()."""
    args = request.args

    def _f(name):
        v = args.get(name)
        if v in (None, "", "null"):
            return None
        try:
            return float(v)
        except ValueError:
            return None

    def _s(name):
        v = args.get(name)
        return v if v not in (None, "", "all", "All") else None

    # Map camelCase sort keys the frontend may send to DB column names.
    sort_by = args.get("sortBy") or "graham_pct"
    sort_alias = {
        "ivGrowth5yr": "iv_cagr_5yr",
        "ivGrowth10yr": "iv_cagr_10yr",
        "ivStability": "iv_stability",
        "marketCap": "market_cap",
        "grahamPct": "graham_pct",
        "fisherPct": "fisher_pct",
        "discount": "discount_to_intrinsic",
    }
    sort_by = sort_alias.get(sort_by, sort_by)

    # IV trend filter comes in as Growing/Stable/Declining; DB stores lowercase.
    iv_trend = _s("ivTrend")
    if iv_trend:
        iv_trend = iv_trend.lower()

    return {
        "sector": _s("sector"),
        "industry": _s("industry"),
        "cap_min": _f("capMin"),
        "cap_max": _f("capMax"),
        "graham_grade": _s("grahamGrade"),
        "fisher_grade": _s("fisherGrade"),
        "min_graham_score": _f("minGrahamScore"),
        "min_fisher_score": _f("minFisherScore"),
        "signal": _s("signal"),
        "min_discount": _f("minDiscount"),
        "iv_trend": iv_trend,
        "sort_by": sort_by,
        "sort_dir": args.get("sortDir") or "DESC",
        "limit": int(args.get("limit", "50")),
    }


@app.route("/api/screen")
def screen():
    """DB-backed screener. Pure SQL query, no API calls.

    If the DB is empty AND an apikey is provided, fall back to the original
    FMP-based screener so the system still works before any ingest has run.
    """
    stats = models.db_stats()
    if stats["companies"] == 0:
        # Fallback to FMP-based screener.
        return _legacy_fmp_screen()

    params = _parse_screen_params()
    rows = models.screen_companies(**params)

    # Match the camelCase shape the existing frontend renders.
    return jsonify([
        {
            "symbol": r["symbol"],
            "companyName": r.get("name"),
            "sector": r.get("sector"),
            "industry": r.get("industry"),
            "marketCap": r.get("market_cap"),
            "price": r.get("price"),
            "grahamGrade": r.get("graham_grade"),
            "grahamPct": r.get("graham_pct"),
            "grahamTotal": r.get("graham_total"),
            "fisherGrade": r.get("fisher_grade"),
            "fisherPct": r.get("fisher_pct"),
            "fisherTotal": r.get("fisher_total"),
            "intrinsicValue": r.get("intrinsic_value_composite"),
            "discount": r.get("discount_to_intrinsic"),
            "signal": r.get("signal"),
            "ivCagr5yr": r.get("iv_cagr_5yr"),
            "ivCagr10yr": r.get("iv_cagr_10yr"),
            "ivTrend": r.get("iv_trend"),
            "ivStability": r.get("iv_stability"),
            "lastComputed": r.get("last_computed"),
        }
        for r in rows
    ])


@app.route("/api/screen/export")
def screen_export():
    """CSV export of the screener results, same filters as /api/screen."""
    params = _parse_screen_params()
    rows = models.screen_companies(**params)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "symbol", "name", "sector", "industry", "market_cap", "price",
        "graham_grade", "graham_pct", "fisher_grade", "fisher_pct",
        "intrinsic_value_composite", "discount_to_intrinsic", "signal",
        "iv_cagr_5yr", "iv_cagr_10yr", "iv_trend", "iv_stability",
        "last_computed",
    ])
    for r in rows:
        writer.writerow([
            r.get("symbol"), r.get("name"), r.get("sector"), r.get("industry"),
            r.get("market_cap"), r.get("price"),
            r.get("graham_grade"), r.get("graham_pct"),
            r.get("fisher_grade"), r.get("fisher_pct"),
            r.get("intrinsic_value_composite"), r.get("discount_to_intrinsic"),
            r.get("signal"),
            r.get("iv_cagr_5yr"), r.get("iv_cagr_10yr"),
            r.get("iv_trend"), r.get("iv_stability"),
            r.get("last_computed"),
        ])
    csv_text = buf.getvalue()
    filename = f"screen_{dt.date.today().isoformat()}.csv"
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _legacy_fmp_screen():
    """The original FMP-based screener. Used only when the DB is empty."""
    apikey = request.args.get("apikey")
    if not apikey:
        return jsonify({
            "error": "Database is empty. Run an ingestion first (py -m ingestion.bulk_ingest --universe starter) "
                     "or pass apikey to use the FMP fallback."
        }), 400

    sector = request.args.get("sector", "")
    if sector and sector in STOCK_UNIVERSE:
        symbols = STOCK_UNIVERSE[sector]
    else:
        symbols = []
        for s in STOCK_UNIVERSE.values():
            symbols.extend(s[:10])

    results = []
    for sym in symbols:
        try:
            profile_list = fmp_get("/profile", apikey, {"symbol": sym})
            if profile_list and isinstance(profile_list, list) and profile_list:
                p = profile_list[0]
                results.append({
                    "symbol": p.get("symbol"),
                    "companyName": p.get("companyName"),
                    "price": p.get("price"),
                    "marketCap": p.get("marketCap"),
                    "sector": p.get("sector"),
                    "industry": p.get("industry"),
                    "beta": p.get("beta"),
                    "averageVolume": p.get("averageVolume"),
                    "exchange": p.get("exchange"),
                })
        except Exception:
            continue

    cap_min = request.args.get("capMin")
    cap_max = request.args.get("capMax")
    if cap_min:
        results = [r for r in results if r.get("marketCap") and r["marketCap"] >= float(cap_min)]
    if cap_max:
        results = [r for r in results if r.get("marketCap") and r["marketCap"] <= float(cap_max)]

    limit = int(request.args.get("limit", "50"))
    return jsonify(results[:limit])


# ---------- Analyze ----------

@app.route("/api/analyze/<symbol>")
def analyze(symbol):
    """Analyze a single ticker.

    Strategy:
      1. If DB has a fresh company + financials, build the FMP-shaped
         dicts from the local DB and run the analysis engines on them.
      2. If DB has no data for this ticker, trigger a single-company
         ingest (slow first time, instant after) — unless the user
         explicitly requested ?source=fmp, in which case use the
         legacy FMP path (apikey required).
    """
    symbol = symbol.upper()
    source = request.args.get("source", "auto")  # auto | local | fmp
    force_refresh = request.args.get("refresh") == "1"

    if source == "fmp":
        return _legacy_fmp_analyze(symbol)

    company = models.get_company(symbol)
    fresh = company and _is_fresh(company.get("last_profile_update"))

    if (not company) or force_refresh or (not fresh and source == "auto"):
        # Trigger a single-company ingest. This is what the spec calls
        # "first analysis of a new company is slow, subsequent ones instant."
        try:
            log.info("[%s] not in DB or stale — running ingest_company()", symbol)
            status = bulk_ingest.ingest_company(symbol)
            if not status.get("ok"):
                # If the user gave an apikey and ingestion failed, try FMP fallback.
                if request.args.get("apikey"):
                    log.warning("[%s] DB ingest failed (%s) — falling back to FMP", symbol, status["errors"])
                    return _legacy_fmp_analyze(symbol)
                return jsonify({
                    "error": f"Ingestion failed for {symbol}",
                    "details": status.get("errors", []),
                }), 502
            company = models.get_company(symbol)
        except Exception as e:
            log.exception("[%s] ingestion crashed", symbol)
            if request.args.get("apikey"):
                return _legacy_fmp_analyze(symbol)
            return jsonify({"error": str(e)}), 500

    if not company:
        return jsonify({"error": f"No data for {symbol}"}), 404

    financials = models.get_financials(symbol, limit=20)
    if not financials:
        return jsonify({
            "error": f"Company {symbol} has profile data but no financial statements (EDGAR mapping may have missed this filer)",
        }), 502

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

    # ---- Phase 3: IV trends + industry model accuracy ----
    iv_trends_payload = _build_iv_trends(symbol, company, financials)
    _augment_valuation_with_accuracy(symbol, company, valuation)

    return jsonify({
        "symbol": symbol,
        "source": "local",
        "lastProfileUpdate": company.get("last_profile_update"),
        "profile": inputs["profile"],
        "graham": graham,
        "fisher": fisher,
        "valuation": valuation,
        "ivTrends": iv_trends_payload,
        "raw": {
            "income": inputs["income"],
            "balance": inputs["balance"],
            "cashflow": inputs["cashflow"],
            "ratios": [],  # FMP-only; not in DB
            "keyMetrics": inputs["key_metrics"],
        },
    })


def _build_iv_trends(symbol, company, financials):
    """Assemble the ivTrends payload for /api/analyze.

    Prefers stored historical_valuations (fast); recomputes on the fly if
    none are stored yet. Returns None if we can't build anything useful.
    """
    from analysis import iv_trends

    stored = models.get_historical_valuations(symbol)
    if stored:
        # Rebuild the per-year structure from stored rows.
        by_year = {}
        for row in stored:
            yr = row["fiscal_year"]
            by_year.setdefault(yr, {})[row["model"]] = row.get("intrinsic_value")

        # avg_price per year from daily_prices.
        prices = models.get_daily_prices(symbol)
        history = []
        model_history = {m: [] for m in iv_trends.MODELS}
        for yr in sorted(by_year):
            model_vals = by_year[yr]
            positives = [v for v in model_vals.values() if v is not None and v > 0]
            composite = round(sum(positives) / len(positives), 2) if positives else None
            avg_price = iv_trends._avg_price_for_year(prices, yr)
            history.append({
                "fiscal_year": yr,
                "composite": composite,
                "avg_price": round(avg_price, 2) if avg_price is not None else None,
            })
            for m in iv_trends.MODELS:
                model_history[m].append(model_vals.get(m))

        # Growth rate from the composite series.
        growth = iv_trends.compute_iv_growth_rate(history)
    else:
        # Nothing stored — compute live (also covers freshly analyzed tickers).
        prices = models.get_daily_prices(symbol)
        computed = iv_trends.compute_historical_valuations(
            symbol, financials, company, daily_prices=prices
        )
        if not computed:
            return None
        history = [
            {"fiscal_year": h["fiscal_year"], "composite": h["composite"],
             "avg_price": h["avg_price"]}
            for h in computed
        ]
        model_history = {m: [] for m in iv_trends.MODELS}
        for h in computed:
            for m in iv_trends.MODELS:
                model_history[m].append(h["models"].get(m, {}).get("intrinsic_value"))
        growth = iv_trends.compute_iv_growth_rate(computed)

    if not history:
        return None

    return {
        "history": history,
        "growthRate": {
            "cagr_5yr": growth.get("cagr_5yr"),
            "cagr_10yr": growth.get("cagr_10yr"),
            "trend": growth.get("trend"),
            "stability": growth.get("stability"),
            "recent_direction": growth.get("recent_direction"),
        },
        "modelHistory": model_history,
    }


def _augment_valuation_with_accuracy(symbol, company, valuation):
    """Add modelAccuracy + weightedValue/weightedSignal to the valuation dict
    in place, using the company's industry model weights (if computed)."""
    from analysis import model_accuracy as ma

    industry = company.get("industry")
    if not industry:
        return

    rows = models.get_model_accuracy(industry)
    if not rows:
        return

    weights = {r["model"]: (r.get("recommended_weight") or 0.0) for r in rows}
    rankings = {
        r["model"]: {
            "avgError3yr": r.get("avg_error_3yr"),
            "rank": r.get("rank_3yr"),
            "weight": r.get("recommended_weight"),
            "sampleSize": r.get("sample_size"),
        }
        for r in rows
    }
    best = next((r["model"] for r in rows if r.get("rank_3yr") == 1), None)
    worst = max(rows, key=lambda r: (r.get("rank_3yr") or 0)).get("model") if rows else None

    weighted = ma.compute_weighted_intrinsic_value(symbol, valuation, weights)

    price = valuation.get("currentPrice")
    weighted_signal = None
    if weighted and price and price > 0:
        wd = (weighted - price) / weighted * 100
        if wd > 35:
            weighted_signal = "STRONG BUY"
        elif wd > 20:
            weighted_signal = "BUY"
        elif wd > 0:
            weighted_signal = "HOLD"
        elif wd > -20:
            weighted_signal = "OVERVALUED"
        else:
            weighted_signal = "STRONG SELL"

    valuation["weightedValue"] = weighted
    valuation["weightedSignal"] = weighted_signal
    valuation["industryWeights"] = weights
    valuation["modelAccuracy"] = {
        "industry": industry,
        "bestModel3yr": best,
        "worstModel3yr": worst,
        "rankings": rankings,
    }


def _legacy_fmp_analyze(symbol):
    apikey = request.args.get("apikey")
    if not apikey:
        return jsonify({"error": "apikey required for FMP fallback"}), 400

    endpoints = {
        "profile": ("/profile", {"symbol": symbol}),
        "income": ("/income-statement", {"symbol": symbol, "period": "annual", "limit": FMP_STMT_LIMIT}),
        "balance": ("/balance-sheet-statement", {"symbol": symbol, "period": "annual", "limit": FMP_STMT_LIMIT}),
        "cashflow": ("/cash-flow-statement", {"symbol": symbol, "period": "annual", "limit": FMP_STMT_LIMIT}),
        "ratios": ("/ratios", {"symbol": symbol, "period": "annual", "limit": FMP_STMT_LIMIT}),
        "keyMetrics": ("/key-metrics", {"symbol": symbol, "period": "annual", "limit": FMP_STMT_LIMIT}),
    }

    data = {"symbol": symbol}
    for key, (path, params) in endpoints.items():
        try:
            data[key] = fmp_get(path, apikey, params)
        except requests.exceptions.HTTPError as e:
            return jsonify({"error": f"FMP API error on {key}: {e.response.status_code}"}), e.response.status_code
        except Exception as e:
            return jsonify({"error": f"Error fetching {key}: {str(e)}"}), 500

    graham = score_graham(data["profile"], data["income"], data["balance"], data["cashflow"], data["keyMetrics"])
    fisher = score_fisher(data["profile"], data["income"], data["balance"], data["cashflow"])
    valuation = compute_valuations(data["profile"], data["income"], data["balance"], data["cashflow"])

    return jsonify({
        "symbol": symbol,
        "source": "fmp",
        "profile": data["profile"],
        "graham": graham,
        "fisher": fisher,
        "valuation": valuation,
        "raw": {
            "income": data["income"],
            "balance": data["balance"],
            "cashflow": data["cashflow"],
            "ratios": data["ratios"],
            "keyMetrics": data["keyMetrics"],
        },
    })


# ---------- Backtest ----------

@app.route("/api/backtest/<symbol>")
def backtest(symbol):
    """Backtest using DB price history; fall back to FMP only when DB is empty."""
    symbol = symbol.upper()
    margin_of_safety = float(request.args.get("mos", "0.35"))
    sell_premium = float(request.args.get("sellPremium", "0.20"))
    years = int(request.args.get("years", "5"))

    company = models.get_company(symbol)
    db_prices = models.get_daily_prices(symbol)
    db_financials = models.get_financials(symbol, limit=20)

    if company and db_financials and db_prices:
        inputs = to_analysis_inputs(company, db_financials)
        prices = historical_prices_fmp_shape(db_prices) or []
        result = run_backtest(
            profile=inputs["profile"],
            income=inputs["income"],
            historical_prices=prices,
            margin_of_safety=margin_of_safety,
            sell_premium=sell_premium,
            years=years,
        )
        return jsonify(result)

    # Fallback to FMP
    apikey = request.args.get("apikey")
    if not apikey:
        return jsonify({
            "error": f"No local data for {symbol}. Ingest first or pass apikey for FMP fallback.",
        }), 400

    try:
        income = fmp_get("/income-statement", apikey, {"symbol": symbol, "period": "annual", "limit": FMP_STMT_LIMIT})
        profile = fmp_get("/profile", apikey, {"symbol": symbol})
        prices = fmp_get("/historical-price-eod/full", apikey, {"symbol": symbol, "from": "2010-01-01"})
    except requests.exceptions.HTTPError as e:
        return jsonify({"error": f"FMP API error: {e.response.status_code}"}), e.response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    result = run_backtest(
        profile=profile,
        income=income,
        historical_prices=prices,
        margin_of_safety=margin_of_safety,
        sell_premium=sell_premium,
        years=years,
    )
    return jsonify(result)


# ---------- Ingest trigger ----------

@app.route("/api/ingest", methods=["POST"])
def ingest():
    """Trigger ingestion for the given symbols or a preset universe.

    Body: {"symbols": ["AAPL", ...]}  OR  {"universe": "starter" | "sp500"}
    Response: {results: [{symbol, ok, errors, stages}, ...]}
    """
    body = request.get_json(silent=True) or {}
    symbols = body.get("symbols") or []
    universe = body.get("universe")

    if universe == "starter":
        symbols = bulk_ingest.get_starter_tickers()
    elif universe == "sp500":
        symbols = bulk_ingest.get_sp500_tickers()

    if not symbols:
        return jsonify({"error": "supply 'symbols' (list) or 'universe' (starter|sp500)"}), 400

    skip_existing = bool(body.get("skipExisting", True))
    results = bulk_ingest.bulk_ingest(symbols, skip_existing=skip_existing)
    ok = sum(1 for r in results if r.get("ok"))
    return jsonify({
        "submitted": len(results),
        "ok": ok,
        "failed": len(results) - ok,
        "results": results,
    })


# ---------- Sectors list (for the UI dropdown) ----------

@app.route("/api/sectors")
def sectors():
    """Distinct sectors present in the DB (for the screener dropdown)."""
    rows = get_db().execute(
        "SELECT DISTINCT sector FROM companies WHERE sector IS NOT NULL ORDER BY sector"
    ).fetchall()
    db_sectors = [r["sector"] for r in rows]
    if db_sectors:
        return jsonify(db_sectors)
    # Fallback to the legacy curated list when DB is empty.
    return jsonify(sorted(STOCK_UNIVERSE.keys()))


# ---------- Industries (Phase 3) ----------

@app.route("/api/industries")
def industries():
    """Distinct industries with company counts.

    Query params:
      sector    optional filter to one sector
      min_count minimum companies per industry (default 5)
    """
    sector = request.args.get("sector") or None
    try:
        min_count = int(request.args.get("min_count", "5"))
    except ValueError:
        min_count = 5

    rows = models.get_industries(min_count=min_count)
    if sector:
        rows = [r for r in rows if r.get("sector") == sector]
    return jsonify([
        {"industry": r["industry"], "sector": r.get("sector"), "count": r["count"]}
        for r in rows
    ])


@app.route("/api/industries/<path:industry>/companies")
def industry_companies(industry):
    """Companies in an industry.

    Query params: limit (int), sort_by (market_cap | name).
    """
    limit = request.args.get("limit")
    limit = int(limit) if limit and limit.isdigit() else None
    sort_by = request.args.get("sort_by", "market_cap")

    rows = models.get_companies_by_industry(industry, limit=limit)
    if sort_by == "name":
        rows.sort(key=lambda r: (r.get("name") or "").lower())
    # market_cap DESC is already the DB default ordering.

    return jsonify([
        {
            "symbol": r["symbol"],
            "companyName": r.get("name"),
            "sector": r.get("sector"),
            "industry": r.get("industry"),
            "marketCap": r.get("market_cap"),
            "price": r.get("price"),
            "exchange": r.get("exchange"),
        }
        for r in rows
    ])


@app.route("/api/industries/<path:industry>/status")
def industry_status(industry):
    """Ingestion status for an industry (profile-only vs deep vs scored)."""
    return jsonify(models.get_ingestion_status(industry))


@app.route("/api/industries/<path:industry>/accuracy")
def industry_accuracy(industry):
    """Model accuracy rankings for an industry (from the model_accuracy table).

    If nothing is stored yet, compute + store it on demand (no API calls).
    """
    rows = models.get_model_accuracy(industry)
    if not rows:
        try:
            from analysis import model_accuracy as ma
            ma.store_industry_model_accuracy(industry)
            rows = models.get_model_accuracy(industry)
        except Exception as e:
            log.exception("[%s] on-demand accuracy computation failed", industry)
            return jsonify({"error": str(e)}), 500

    if not rows:
        return jsonify({"industry": industry, "rankings": [], "message": "no accuracy data"}), 404

    best = next((r["model"] for r in rows if r.get("rank_3yr") == 1), None)
    return jsonify({
        "industry": industry,
        "bestModel3yr": best,
        "lastComputed": rows[0].get("last_computed"),
        "rankings": [
            {
                "model": r["model"],
                "avgError1yr": r.get("avg_error_1yr"),
                "avgError3yr": r.get("avg_error_3yr"),
                "avgError5yr": r.get("avg_error_5yr"),
                "sampleSize": r.get("sample_size"),
                "rank": r.get("rank_3yr"),
                "recommendedWeight": r.get("recommended_weight"),
            }
            for r in rows
        ],
    })


# ---------- Ingest triggers (Phase 3) ----------

@app.route("/api/ingest/discover", methods=["POST"])
def ingest_discover():
    """Light-ingest the US-listed universe to build the industry catalog.

    Runs synchronously. Body (optional): {"sample": N} to limit for testing.
    Returns a count of companies light-ingested.
    """
    body = request.get_json(silent=True) or {}
    sample = body.get("sample")
    sample = int(sample) if sample else None
    try:
        n = bulk_ingest.discover_universe(sample=sample)
        return jsonify({"ok": True, "ingested": n})
    except Exception as e:
        log.exception("discover-universe failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/ingest/industry", methods=["POST"])
def ingest_industry():
    """Deep-ingest all companies in an industry (EDGAR + prices + scores),
    then compute per-industry model accuracy.

    Body: {"industry": "Banks - Regional", "limit": 100}
    """
    body = request.get_json(silent=True) or {}
    industry = body.get("industry")
    if not industry:
        return jsonify({"error": "body must include 'industry'"}), 400
    limit = body.get("limit")
    limit = int(limit) if limit else None

    try:
        summary = bulk_ingest.deep_ingest_industry(industry, limit=limit)
        return jsonify({"ok": summary["failed"] == 0, **summary})
    except Exception as e:
        log.exception("[%s] deep ingest failed", industry)
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app.run(debug=True, port=5000)
