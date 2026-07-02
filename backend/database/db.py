"""SQLite connection manager and schema initialization.

The database file lives next to this module at value_investor.db.
WAL mode is enabled for better concurrent read performance (the Flask
app reads while ingestion writes).
"""

import os
import sqlite3
import threading

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "value_investor.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    symbol TEXT PRIMARY KEY,
    name TEXT,
    sector TEXT,
    industry TEXT,
    exchange TEXT,
    market_cap REAL,
    price REAL,
    shares_outstanding REAL,
    beta REAL,
    dividend_yield REAL,
    description TEXT,
    cik TEXT,
    last_profile_update TEXT
);

CREATE TABLE IF NOT EXISTS financials (
    symbol TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    fiscal_date TEXT,
    source TEXT,

    revenue REAL,
    cost_of_revenue REAL,
    gross_profit REAL,
    operating_income REAL,
    net_income REAL,
    eps REAL,
    eps_diluted REAL,
    research_and_development REAL,
    sga_expense REAL,
    weighted_avg_shares REAL,
    weighted_avg_shares_diluted REAL,

    total_assets REAL,
    total_current_assets REAL,
    total_liabilities REAL,
    total_current_liabilities REAL,
    total_debt REAL,
    total_stockholders_equity REAL,
    retained_earnings REAL,
    cash_and_equivalents REAL,

    operating_cash_flow REAL,
    capital_expenditure REAL,
    free_cash_flow REAL,
    dividends_paid REAL,

    current_ratio REAL,
    debt_to_equity REAL,
    gross_margin REAL,
    operating_margin REAL,
    net_margin REAL,
    roe REAL,
    roa REAL,
    fcf_margin REAL,

    fetched_at TEXT,

    PRIMARY KEY (symbol, fiscal_year)
);

CREATE TABLE IF NOT EXISTS daily_prices (
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    adj_close REAL,
    volume INTEGER,
    PRIMARY KEY (symbol, date)
);

CREATE TABLE IF NOT EXISTS scores (
    symbol TEXT PRIMARY KEY,

    graham_total REAL,
    graham_max REAL,
    graham_pct REAL,
    graham_grade TEXT,
    graham_details TEXT,

    fisher_total REAL,
    fisher_max REAL,
    fisher_pct REAL,
    fisher_grade TEXT,
    fisher_details TEXT,

    intrinsic_value_graham REAL,
    intrinsic_value_dcf REAL,
    intrinsic_value_book REAL,
    intrinsic_value_epv REAL,
    intrinsic_value_ncav REAL,
    intrinsic_value_composite REAL,
    discount_to_intrinsic REAL,
    signal TEXT,

    iv_cagr_5yr REAL,
    iv_cagr_10yr REAL,
    iv_trend TEXT,
    iv_stability REAL,

    last_computed TEXT
);

CREATE TABLE IF NOT EXISTS historical_valuations (
    symbol TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    model TEXT NOT NULL,        -- "graham", "dcf", "book_value", "epv", "ncav"
    intrinsic_value REAL,       -- Per-share intrinsic value estimate
    inputs TEXT,                -- JSON blob of inputs used (EPS, growth rate, etc.)
    PRIMARY KEY (symbol, fiscal_year, model)
);

CREATE TABLE IF NOT EXISTS model_accuracy (
    industry TEXT NOT NULL,
    model TEXT NOT NULL,           -- "graham", "dcf", "book_value", "epv", "ncav"
    avg_error_1yr REAL,
    avg_error_3yr REAL,
    avg_error_5yr REAL,
    sample_size INTEGER,          -- How many company-years went into this average
    rank_3yr INTEGER,             -- 1 = best model for this industry
    recommended_weight REAL,      -- 0.0 to 1.0
    last_computed TEXT,            -- ISO datetime
    PRIMARY KEY (industry, model)
);

CREATE INDEX IF NOT EXISTS idx_companies_sector ON companies(sector);
CREATE INDEX IF NOT EXISTS idx_companies_industry ON companies(industry);
CREATE INDEX IF NOT EXISTS idx_companies_market_cap ON companies(market_cap);
CREATE INDEX IF NOT EXISTS idx_financials_symbol ON financials(symbol);
CREATE INDEX IF NOT EXISTS idx_daily_prices_symbol_date ON daily_prices(symbol, date);
CREATE INDEX IF NOT EXISTS idx_scores_graham_grade ON scores(graham_grade);
CREATE INDEX IF NOT EXISTS idx_scores_signal ON scores(signal);
CREATE INDEX IF NOT EXISTS idx_hist_val_symbol ON historical_valuations(symbol);
"""

# Indexes that reference columns added by _MIGRATIONS. These must run AFTER
# migrations so an existing DB has the column before the index is built.
_POST_MIGRATION_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_scores_iv_trend ON scores(iv_trend);
"""

# Columns added after the initial Phase 2 release. For databases created
# before Phase 3, CREATE TABLE IF NOT EXISTS won't add these, so we ALTER
# them in idempotently on every connection. (table, column, type)
_MIGRATIONS = [
    ("scores", "iv_cagr_5yr", "REAL"),
    ("scores", "iv_cagr_10yr", "REAL"),
    ("scores", "iv_trend", "TEXT"),
    ("scores", "iv_stability", "REAL"),
]


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Add any columns missing from an older database, then build indexes
    that depend on those columns. Idempotent."""
    for table, column, coltype in _MIGRATIONS:
        cols = {
            r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
    conn.executescript(_POST_MIGRATION_SCHEMA)
    conn.commit()

_local = threading.local()


def get_db() -> sqlite3.Connection:
    """Return a SQLite connection scoped to the current thread.

    Rows are returned as sqlite3.Row so callers can access columns by name.
    The schema is initialized on first connection per thread.
    """
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_SCHEMA)
        conn.commit()
        _run_migrations(conn)
        _local.conn = conn
    return conn


def init_db() -> None:
    """Force schema creation. Useful from CLI / first-run scripts."""
    conn = get_db()
    conn.executescript(_SCHEMA)
    conn.commit()
    _run_migrations(conn)


def close_db() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None
