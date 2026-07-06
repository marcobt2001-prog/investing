"""Helper queries for the value-investor SQLite database.

Each function takes plain Python kwargs and handles upsert / read for
one of the four tables: companies, financials, daily_prices, scores.

Functions return dicts (not sqlite3.Row) so callers can json-serialize
results without further conversion.
"""

from __future__ import annotations

import datetime as _dt
import json as _json
from typing import Any, Iterable, Optional

from .db import get_db


_COMPANY_COLUMNS = {
    "symbol", "name", "sector", "industry", "exchange", "market_cap",
    "price", "shares_outstanding", "beta", "dividend_yield", "description",
    "cik", "last_profile_update",
}

_FINANCIAL_COLUMNS = {
    "symbol", "fiscal_year", "fiscal_date", "source",
    "revenue", "cost_of_revenue", "gross_profit", "operating_income",
    "net_income", "eps", "eps_diluted", "research_and_development",
    "sga_expense", "weighted_avg_shares", "weighted_avg_shares_diluted",
    "total_assets", "total_current_assets", "total_liabilities",
    "total_current_liabilities", "total_debt", "total_stockholders_equity",
    "retained_earnings", "cash_and_equivalents",
    "operating_cash_flow", "capital_expenditure", "free_cash_flow",
    "dividends_paid",
    "current_ratio", "debt_to_equity", "gross_margin", "operating_margin",
    "net_margin", "roe", "roa", "fcf_margin",
    "fetched_at",
}

_PRICE_COLUMNS = {
    "symbol", "date", "open", "high", "low", "close", "adj_close", "volume",
}

_SCORE_COLUMNS = {
    "symbol",
    "graham_total", "graham_max", "graham_pct", "graham_grade", "graham_details",
    "fisher_total", "fisher_max", "fisher_pct", "fisher_grade", "fisher_details",
    "intrinsic_value_graham", "intrinsic_value_dcf", "intrinsic_value_book",
    "intrinsic_value_epv", "intrinsic_value_ncav", "intrinsic_value_composite",
    "discount_to_intrinsic", "signal",
    "iv_cagr_5yr", "iv_cagr_10yr", "iv_trend", "iv_stability",
    "graham_completeness", "fisher_completeness",
    "last_computed",
}

_HISTORICAL_VALUATION_COLUMNS = {
    "symbol", "fiscal_year", "model", "intrinsic_value", "inputs",
}

_MODEL_ACCURACY_COLUMNS = {
    "industry", "model", "avg_error_1yr", "avg_error_3yr", "avg_error_5yr",
    "sample_size", "rank_3yr", "recommended_weight", "last_computed",
}

_LLM_EVALUATION_COLUMNS = {
    "symbol", "evaluation", "provider", "model", "quality_score",
    "overall_risk", "moat_type", "moat_durability", "confidence", "created_at",
}


def _now_iso() -> str:
    return _dt.datetime.utcnow().isoformat(timespec="seconds")


def _filter_kwargs(kwargs: dict, allowed: set) -> dict:
    return {k: v for k, v in kwargs.items() if k in allowed}


def _upsert(table: str, key_cols: list[str], data: dict) -> None:
    """Generic INSERT ... ON CONFLICT(key_cols) DO UPDATE SET ..."""
    if not data:
        return
    cols = list(data.keys())
    placeholders = ",".join("?" for _ in cols)
    update_cols = [c for c in cols if c not in key_cols]
    set_clause = ", ".join(f"{c}=excluded.{c}" for c in update_cols)
    conflict_cols = ", ".join(key_cols)

    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
    if update_cols:
        sql += f" ON CONFLICT({conflict_cols}) DO UPDATE SET {set_clause}"
    else:
        sql += f" ON CONFLICT({conflict_cols}) DO NOTHING"

    conn = get_db()
    conn.execute(sql, [data[c] for c in cols])
    conn.commit()


# ---------- companies ----------

def upsert_company(symbol: str, **fields) -> None:
    data = _filter_kwargs(fields, _COMPANY_COLUMNS)
    data["symbol"] = symbol.upper()
    if "last_profile_update" not in data:
        data["last_profile_update"] = _now_iso()
    _upsert("companies", ["symbol"], data)


def get_company(symbol: str) -> Optional[dict]:
    row = get_db().execute(
        "SELECT * FROM companies WHERE symbol = ?", (symbol.upper(),)
    ).fetchone()
    return dict(row) if row else None


def search_companies(query: str, limit: int = 25) -> list[dict]:
    """LIKE-search by symbol or name. Case-insensitive."""
    q = f"%{query.lower()}%"
    rows = get_db().execute(
        """
        SELECT * FROM companies
        WHERE LOWER(symbol) LIKE ? OR LOWER(name) LIKE ?
        ORDER BY market_cap DESC NULLS LAST
        LIMIT ?
        """,
        (q, q, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------- financials ----------

def upsert_financials(symbol: str, fiscal_year: int, **fields) -> None:
    data = _filter_kwargs(fields, _FINANCIAL_COLUMNS)
    data["symbol"] = symbol.upper()
    data["fiscal_year"] = int(fiscal_year)
    if "fetched_at" not in data:
        data["fetched_at"] = _now_iso()
    _upsert("financials", ["symbol", "fiscal_year"], data)


def get_financials(symbol: str, limit: int = 12) -> list[dict]:
    rows = get_db().execute(
        """
        SELECT * FROM financials
        WHERE symbol = ?
        ORDER BY fiscal_year DESC
        LIMIT ?
        """,
        (symbol.upper(), limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------- daily prices ----------

def upsert_daily_prices(symbol: str, rows: Iterable[dict]) -> int:
    """Bulk upsert price rows. Returns count of rows written."""
    sym = symbol.upper()
    payload = []
    for r in rows:
        d = _filter_kwargs(r, _PRICE_COLUMNS)
        d["symbol"] = sym
        if "date" not in d:
            continue
        payload.append(d)

    if not payload:
        return 0

    cols = list(payload[0].keys())
    placeholders = ",".join("?" for _ in cols)
    update_cols = [c for c in cols if c not in ("symbol", "date")]
    set_clause = ", ".join(f"{c}=excluded.{c}" for c in update_cols)
    sql = (
        f"INSERT INTO daily_prices ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(symbol, date) DO UPDATE SET {set_clause}"
    )

    conn = get_db()
    conn.executemany(sql, [[row.get(c) for c in cols] for row in payload])
    conn.commit()
    return len(payload)


def get_daily_prices(symbol: str, start_date: Optional[str] = None) -> list[dict]:
    sql = "SELECT * FROM daily_prices WHERE symbol = ?"
    params: list[Any] = [symbol.upper()]
    if start_date:
        sql += " AND date >= ?"
        params.append(start_date)
    sql += " ORDER BY date ASC"
    rows = get_db().execute(sql, params).fetchall()
    return [dict(r) for r in rows]


# ---------- scores ----------

def upsert_scores(symbol: str, **fields) -> None:
    data = _filter_kwargs(fields, _SCORE_COLUMNS)
    data["symbol"] = symbol.upper()
    if "last_computed" not in data:
        data["last_computed"] = _now_iso()
    _upsert("scores", ["symbol"], data)


def get_scores(symbol: str) -> Optional[dict]:
    row = get_db().execute(
        "SELECT * FROM scores WHERE symbol = ?", (symbol.upper(),)
    ).fetchone()
    return dict(row) if row else None


# ---------- historical valuations ----------

def upsert_historical_valuation(
    symbol: str, fiscal_year: int, model: str,
    intrinsic_value: Optional[float], inputs: Any = None,
) -> None:
    """Store one model's intrinsic value for one company-year.

    `inputs` may be a dict (json-encoded automatically) or a pre-serialized
    string. None is stored as SQL NULL.
    """
    if inputs is not None and not isinstance(inputs, str):
        inputs = _json.dumps(inputs)
    data = {
        "symbol": symbol.upper(),
        "fiscal_year": int(fiscal_year),
        "model": model,
        "intrinsic_value": intrinsic_value,
        "inputs": inputs,
    }
    _upsert("historical_valuations", ["symbol", "fiscal_year", "model"], data)


def get_historical_valuations(symbol: str) -> list[dict]:
    """All stored historical valuations for a company, oldest year first.

    The `inputs` JSON blob is decoded back into a dict where possible.
    """
    rows = get_db().execute(
        """
        SELECT * FROM historical_valuations
        WHERE symbol = ?
        ORDER BY fiscal_year ASC, model ASC
        """,
        (symbol.upper(),),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("inputs"):
            try:
                d["inputs"] = _json.loads(d["inputs"])
            except (ValueError, TypeError):
                pass
        out.append(d)
    return out


# ---------- model accuracy ----------

def upsert_model_accuracy(industry: str, model: str, **fields) -> None:
    data = _filter_kwargs(fields, _MODEL_ACCURACY_COLUMNS)
    data["industry"] = industry
    data["model"] = model
    if "last_computed" not in data:
        data["last_computed"] = _now_iso()
    _upsert("model_accuracy", ["industry", "model"], data)


def get_model_accuracy(industry: str) -> list[dict]:
    """Model accuracy rows for an industry, best (rank 1) first."""
    rows = get_db().execute(
        """
        SELECT * FROM model_accuracy
        WHERE industry = ?
        ORDER BY rank_3yr ASC NULLS LAST
        """,
        (industry,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------- llm evaluations ----------

def upsert_llm_evaluation(
    symbol: str, evaluation: Any, provider: str, model: Optional[str],
    quality_score: Optional[int] = None, overall_risk: Optional[str] = None,
    moat_type: Optional[str] = None, moat_durability: Optional[str] = None,
    confidence: Optional[str] = None,
) -> None:
    """Cache one LLM qualitative evaluation for a company.

    `evaluation` may be a dict (json-encoded automatically) or a pre-serialized
    string. The scalar columns (quality_score, overall_risk, etc.) are pulled
    out for cheap screener filtering without re-parsing the JSON blob.
    """
    if evaluation is not None and not isinstance(evaluation, str):
        evaluation = _json.dumps(evaluation)
    data = {
        "symbol": symbol.upper(),
        "evaluation": evaluation,
        "provider": provider,
        "model": model,
        "quality_score": quality_score,
        "overall_risk": overall_risk,
        "moat_type": moat_type,
        "moat_durability": moat_durability,
        "confidence": confidence,
        "created_at": _now_iso(),
    }
    _upsert("llm_evaluations", ["symbol"], data)


def get_llm_evaluation(symbol: str) -> Optional[dict]:
    """Return the cached LLM evaluation for a company, or None.

    The `evaluation` JSON blob is decoded back into a dict where possible.
    """
    row = get_db().execute(
        "SELECT * FROM llm_evaluations WHERE symbol = ?", (symbol.upper(),)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("evaluation"):
        try:
            d["evaluation"] = _json.loads(d["evaluation"])
        except (ValueError, TypeError):
            pass
    return d


# ---------- industries ----------

def get_industries(min_count: int = 5) -> list[dict]:
    """Distinct industries with company counts, most-populous first.

    Only industries with at least `min_count` companies are returned.
    """
    rows = get_db().execute(
        """
        SELECT industry, sector, COUNT(*) AS count
        FROM companies
        WHERE industry IS NOT NULL AND industry != ''
        GROUP BY industry
        HAVING COUNT(*) >= ?
        ORDER BY count DESC
        """,
        (min_count,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_sectors() -> list[dict]:
    """Distinct sectors with industry counts and company counts."""
    rows = get_db().execute(
        """
        SELECT sector,
               COUNT(DISTINCT industry) AS industry_count,
               COUNT(*) AS company_count
        FROM companies
        WHERE sector IS NOT NULL AND sector != ''
        GROUP BY sector
        ORDER BY company_count DESC
        """,
    ).fetchall()
    return [dict(r) for r in rows]


def get_companies_by_industry(
    industry: str, limit: Optional[int] = None
) -> list[dict]:
    """All companies in an industry, largest market cap first."""
    sql = """
        SELECT symbol, name, sector, industry, market_cap, price, exchange
        FROM companies
        WHERE industry = ?
        ORDER BY market_cap DESC NULLS LAST
    """
    params: list[Any] = [industry]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    rows = get_db().execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_ingestion_status(industry: str) -> dict:
    """Ingestion progress for an industry.

    Returns counts of companies that are:
    - total: in the industry
    - profile_only: have a profile but no financials (light-ingested)
    - with_financials: have at least one financials row (deep-ingested)
    - with_scores: have a computed scores row
    """
    conn = get_db()
    total = conn.execute(
        "SELECT COUNT(*) FROM companies WHERE industry = ?", (industry,)
    ).fetchone()[0]
    with_financials = conn.execute(
        """
        SELECT COUNT(DISTINCT c.symbol)
        FROM companies c
        JOIN financials f ON f.symbol = c.symbol
        WHERE c.industry = ?
        """,
        (industry,),
    ).fetchone()[0]
    with_scores = conn.execute(
        """
        SELECT COUNT(DISTINCT c.symbol)
        FROM companies c
        JOIN scores s ON s.symbol = c.symbol
        WHERE c.industry = ?
        """,
        (industry,),
    ).fetchone()[0]
    return {
        "industry": industry,
        "total": total,
        "profile_only": total - with_financials,
        "with_financials": with_financials,
        "with_scores": with_scores,
    }


# ---------- screener ----------

def screen_companies(
    sector: Optional[str] = None,
    industry: Optional[str] = None,
    cap_min: Optional[float] = None,
    cap_max: Optional[float] = None,
    graham_grade: Optional[str] = None,
    fisher_grade: Optional[str] = None,
    min_graham_score: Optional[float] = None,
    min_fisher_score: Optional[float] = None,
    signal: Optional[str] = None,
    min_discount: Optional[float] = None,
    iv_trend: Optional[str] = None,
    min_graham_completeness: Optional[float] = None,
    min_fisher_completeness: Optional[float] = None,
    min_quality_score: Optional[int] = None,
    moat_durability: Optional[str] = None,
    overall_risk: Optional[str] = None,
    sort_by: str = "graham_pct",
    sort_dir: str = "DESC",
    limit: int = 50,
) -> list[dict]:
    """Filter/sort across the companies + scores join.

    All filter params are optional. `sort_by` is validated against a
    whitelist; anything else is silently swapped for graham_pct.
    """
    sort_whitelist = {
        "symbol", "name", "sector", "market_cap", "price",
        "graham_pct", "graham_total", "fisher_pct", "fisher_total",
        "intrinsic_value_composite", "discount_to_intrinsic", "signal",
        "iv_cagr_5yr", "iv_cagr_10yr", "iv_stability",
        "quality_score",
    }
    if sort_by not in sort_whitelist:
        sort_by = "graham_pct"
    sort_dir = "ASC" if sort_dir.upper() == "ASC" else "DESC"

    where = []
    params: list[Any] = []

    if sector:
        where.append("c.sector = ?")
        params.append(sector)
    if industry:
        where.append("c.industry = ?")
        params.append(industry)
    if cap_min is not None:
        where.append("c.market_cap >= ?")
        params.append(cap_min)
    if cap_max is not None:
        where.append("c.market_cap <= ?")
        params.append(cap_max)
    if graham_grade:
        where.append("s.graham_grade = ?")
        params.append(graham_grade)
    if fisher_grade:
        where.append("s.fisher_grade = ?")
        params.append(fisher_grade)
    if min_graham_score is not None:
        where.append("s.graham_pct >= ?")
        params.append(min_graham_score)
    if min_fisher_score is not None:
        where.append("s.fisher_pct >= ?")
        params.append(min_fisher_score)
    if signal:
        where.append("s.signal = ?")
        params.append(signal)
    if min_discount is not None:
        where.append("s.discount_to_intrinsic >= ?")
        params.append(min_discount)
    if iv_trend:
        where.append("s.iv_trend = ?")
        params.append(iv_trend)
    if min_graham_completeness is not None:
        where.append("s.graham_completeness >= ?")
        params.append(min_graham_completeness)
    if min_fisher_completeness is not None:
        where.append("s.fisher_completeness >= ?")
        params.append(min_fisher_completeness)
    if min_quality_score is not None:
        where.append("l.quality_score >= ?")
        params.append(min_quality_score)
    if moat_durability:
        where.append("l.moat_durability = ?")
        params.append(moat_durability)
    if overall_risk:
        where.append("l.overall_risk = ?")
        params.append(overall_risk)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    # quality_score lives on the llm_evaluations join; qualify it for ORDER BY.
    sort_col = "l.quality_score" if sort_by == "quality_score" else sort_by

    sql = f"""
        SELECT
            c.symbol, c.name, c.sector, c.industry, c.market_cap, c.price,
            s.graham_total, s.graham_pct, s.graham_grade,
            s.fisher_total, s.fisher_pct, s.fisher_grade,
            s.intrinsic_value_composite, s.discount_to_intrinsic, s.signal,
            s.iv_cagr_5yr, s.iv_cagr_10yr, s.iv_trend, s.iv_stability,
            s.graham_completeness, s.fisher_completeness,
            s.last_computed,
            l.quality_score, l.overall_risk, l.moat_type, l.moat_durability
        FROM companies c
        LEFT JOIN scores s ON s.symbol = c.symbol
        LEFT JOIN llm_evaluations l ON l.symbol = c.symbol
        {where_sql}
        ORDER BY {sort_col} {sort_dir} NULLS LAST
        LIMIT ?
    """
    params.append(limit)

    rows = get_db().execute(sql, params).fetchall()
    return [dict(r) for r in rows]


# ---------- DB stats ----------

def db_stats() -> dict:
    conn = get_db()
    return {
        "companies": conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0],
        "financials_rows": conn.execute("SELECT COUNT(*) FROM financials").fetchone()[0],
        "scores": conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0],
        "daily_prices_rows": conn.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0],
        "earliest_price": conn.execute("SELECT MIN(date) FROM daily_prices").fetchone()[0],
        "latest_price": conn.execute("SELECT MAX(date) FROM daily_prices").fetchone()[0],
        "last_score_computed": conn.execute("SELECT MAX(last_computed) FROM scores").fetchone()[0],
    }
