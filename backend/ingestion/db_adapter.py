"""Adapter: convert DB rows -> the FMP-shaped dict lists the analysis
engines were originally written against.

The existing `analysis/` modules (graham, fisher, valuation, backtest)
read camelCase fields like `netIncome`, `totalStockholdersEquity`,
`freeCashFlow`, `weightedAverageShsOut`, etc., split across separate
profile / income / balance / cashflow / key_metrics lists ordered
most-recent-first.

Our database stores snake_case, flattened to one `financials` row per
fiscal year. This adapter rebuilds the FMP shape from DB rows so we don't
have to touch the analysis code.
"""

from __future__ import annotations

from typing import Optional


def _income_row(fin: dict) -> dict:
    """One FMP-style income statement dict from a DB financials row."""
    return {
        "date": fin.get("fiscal_date"),
        "calendarYear": fin.get("fiscal_year"),
        "revenue": fin.get("revenue"),
        "costOfRevenue": fin.get("cost_of_revenue"),
        "grossProfit": fin.get("gross_profit"),
        "operatingIncome": fin.get("operating_income"),
        "netIncome": fin.get("net_income"),
        "eps": fin.get("eps"),
        "epsdiluted": fin.get("eps_diluted"),
        "researchAndDevelopmentExpenses": fin.get("research_and_development"),
        "sellingGeneralAndAdministrativeExpenses": fin.get("sga_expense"),
        "weightedAverageShsOut": fin.get("weighted_avg_shares"),
        "weightedAverageShsOutDil": fin.get("weighted_avg_shares_diluted"),
    }


def _balance_row(fin: dict) -> dict:
    return {
        "date": fin.get("fiscal_date"),
        "calendarYear": fin.get("fiscal_year"),
        "totalAssets": fin.get("total_assets"),
        "totalCurrentAssets": fin.get("total_current_assets"),
        "totalLiabilities": fin.get("total_liabilities"),
        "totalCurrentLiabilities": fin.get("total_current_liabilities"),
        "totalDebt": fin.get("total_debt"),
        "totalStockholdersEquity": fin.get("total_stockholders_equity"),
        "retainedEarnings": fin.get("retained_earnings"),
        "cashAndCashEquivalents": fin.get("cash_and_equivalents"),
    }


def _cashflow_row(fin: dict) -> dict:
    div = fin.get("dividends_paid")
    # FMP convention: dividendsPaid is negative when dividends are paid out.
    # EDGAR sometimes reports as positive (the cash outflow magnitude). Make
    # sure it ends up negative so graham's dividend-record check matches.
    if div is not None and div > 0:
        div = -div
    return {
        "date": fin.get("fiscal_date"),
        "calendarYear": fin.get("fiscal_year"),
        "operatingCashFlow": fin.get("operating_cash_flow"),
        "capitalExpenditure": fin.get("capital_expenditure"),
        "freeCashFlow": fin.get("free_cash_flow"),
        "dividendsPaid": div,
        "commonDividendsPaid": div,
        "netDividendsPaid": div,
    }


def _profile_dict(company: dict) -> dict:
    """Build the FMP-style profile dict from a companies row."""
    return {
        "symbol": company.get("symbol"),
        "companyName": company.get("name"),
        "sector": company.get("sector"),
        "industry": company.get("industry"),
        "exchange": company.get("exchange"),
        "marketCap": company.get("market_cap"),
        "price": company.get("price"),
        "beta": company.get("beta"),
        "description": company.get("description"),
        "lastDiv": None,
    }


def _key_metrics_row(company: dict, fin: dict) -> dict:
    """Minimal key_metrics shape — graham uses only marketCap from this list."""
    return {
        "date": fin.get("fiscal_date"),
        "calendarYear": fin.get("fiscal_year"),
        "marketCap": company.get("market_cap"),
    }


def to_analysis_inputs(company: dict, financials: list[dict]) -> dict:
    """Build the (profile, income, balance, cashflow, key_metrics) tuple
    expected by the analysis engines.

    Args:
        company: row from the `companies` table (snake_case keys).
        financials: rows from `financials` for that ticker, MOST RECENT FIRST.

    Returns:
        dict with keys: profile, income, balance, cashflow, key_metrics.
        Each is a list. Profile is a single-element list per FMP convention.
    """
    profile = [_profile_dict(company)]
    income = [_income_row(f) for f in financials]
    balance = [_balance_row(f) for f in financials]
    cashflow = [_cashflow_row(f) for f in financials]
    key_metrics = [_key_metrics_row(company, f) for f in financials]

    return {
        "profile": profile,
        "income": income,
        "balance": balance,
        "cashflow": cashflow,
        "key_metrics": key_metrics,
    }


def historical_prices_fmp_shape(price_rows: list[dict]) -> Optional[list[dict]]:
    """The backtest engine reads FMP's historicalPriceFull format. Convert
    DB price rows to that shape (dates DESC). Returns None if empty."""
    if not price_rows:
        return None
    # DB rows come back date ASC; FMP returns most recent first.
    return [
        {
            "date": r["date"],
            "open": r.get("open"),
            "high": r.get("high"),
            "low": r.get("low"),
            "close": r.get("close"),
            "adjClose": r.get("adj_close"),
            "volume": r.get("volume"),
        }
        for r in sorted(price_rows, key=lambda x: x["date"], reverse=True)
    ]
