from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import time

from analysis.graham import score_graham
from analysis.fisher import score_fisher
from analysis.valuation import compute_valuations
from analysis.backtest import run_backtest

app = Flask(__name__)
CORS(app)

FMP_BASE = "https://financialmodelingprep.com/stable"

# Free tier limit for financial statement queries
FMP_STMT_LIMIT = "5"

# Curated stock universe by sector for the screener (free tier has no screener endpoint)
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
    """Helper to make a GET request to the FMP stable API with retry on rate limit."""
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


# ---------- Health check ----------

@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


# ---------- Search ----------

@app.route("/api/search")
def search():
    apikey = request.args.get("apikey")
    if not apikey:
        return jsonify({"error": "apikey query parameter is required"}), 400

    query = request.args.get("query", "")
    if not query:
        return jsonify({"error": "query parameter is required"}), 400

    try:
        results = fmp_get("/search-name", apikey, {"query": query, "limit": "20"})
        # Filter to common US exchanges
        filtered = [r for r in results if r.get("exchange") in {"NASDAQ", "NYSE", "AMEX"}
                    or r.get("exchangeFullName", "").startswith("NASDAQ")
                    or r.get("exchangeFullName", "").startswith("NYSE")
                    or r.get("exchangeFullName", "").startswith("New York")]
        return jsonify(filtered)
    except requests.exceptions.HTTPError as e:
        return jsonify({"error": f"FMP API error: {e.response.status_code}"}), e.response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------- Stock Screener ----------

@app.route("/api/screen")
def screen():
    apikey = request.args.get("apikey")
    if not apikey:
        return jsonify({"error": "apikey query parameter is required"}), 400

    sector = request.args.get("sector", "")

    if sector and sector in STOCK_UNIVERSE:
        symbols = STOCK_UNIVERSE[sector]
    else:
        # All sectors - take top 10 from each
        symbols = []
        for s in STOCK_UNIVERSE.values():
            symbols.extend(s[:10])

    results = []
    for sym in symbols:
        try:
            profile_list = fmp_get("/profile", apikey, {"symbol": sym})
            if profile_list and isinstance(profile_list, list) and len(profile_list) > 0:
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
    apikey = request.args.get("apikey")
    if not apikey:
        return jsonify({"error": "apikey query parameter is required"}), 400

    symbol = symbol.upper()

    # Fetch all financial data from FMP
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

    # Run analysis engines
    graham = score_graham(
        data["profile"], data["income"], data["balance"],
        data["cashflow"], data["keyMetrics"]
    )
    fisher = score_fisher(
        data["profile"], data["income"], data["balance"], data["cashflow"]
    )
    valuation = compute_valuations(
        data["profile"], data["income"], data["balance"], data["cashflow"]
    )

    return jsonify({
        "symbol": symbol,
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
    apikey = request.args.get("apikey")
    if not apikey:
        return jsonify({"error": "apikey query parameter is required"}), 400

    symbol = symbol.upper()
    margin_of_safety = float(request.args.get("mos", "0.35"))
    sell_premium = float(request.args.get("sellPremium", "0.20"))
    years = int(request.args.get("years", "5"))

    try:
        income = fmp_get("/income-statement", apikey, {"symbol": symbol, "period": "annual", "limit": FMP_STMT_LIMIT})
        balance = fmp_get("/balance-sheet-statement", apikey, {"symbol": symbol, "period": "annual", "limit": FMP_STMT_LIMIT})
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


if __name__ == "__main__":
    app.run(debug=True, port=5000)
