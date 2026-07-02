"""Sanity test for Step 1: schema init + CRUD round-trip on every table.

Run from backend/ with:  py test_step1_db.py
"""

import json
import os
import sys

# Run as a script from backend/ — make local imports resolvable.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import db as db_mod
from database import models


def main() -> int:
    # Use a throwaway DB so we don't pollute the real one.
    test_path = os.path.join(os.path.dirname(db_mod.DB_PATH), "test_value_investor.db")
    if os.path.exists(test_path):
        os.remove(test_path)
    db_mod.DB_PATH = test_path

    # Force a fresh thread-local connection bound to the test DB.
    db_mod.close_db()
    db_mod.init_db()

    print(f"DB created at: {test_path}")

    # --- companies ---
    models.upsert_company(
        "AAPL",
        name="Apple Inc.",
        sector="Technology",
        industry="Consumer Electronics",
        exchange="NASDAQ",
        market_cap=3_000_000_000_000,
        price=180.0,
        shares_outstanding=15_500_000_000,
        cik="0000320193",
    )
    aapl = models.get_company("aapl")  # case-insensitive lookup
    assert aapl and aapl["name"] == "Apple Inc.", f"company round-trip failed: {aapl}"
    print(f"companies: upsert+get OK -> {aapl['symbol']} {aapl['name']}")

    # update path
    models.upsert_company("AAPL", price=185.0)
    aapl2 = models.get_company("AAPL")
    assert aapl2["price"] == 185.0 and aapl2["name"] == "Apple Inc."
    print(f"companies: update preserves untouched fields OK (price={aapl2['price']})")

    # --- financials ---
    models.upsert_financials(
        "AAPL",
        2024,
        fiscal_date="2024-09-28",
        source="edgar",
        revenue=391_000_000_000,
        net_income=94_000_000_000,
        eps=6.10,
        total_assets=350_000_000_000,
        total_liabilities=290_000_000_000,
        total_stockholders_equity=60_000_000_000,
    )
    models.upsert_financials("AAPL", 2023, source="edgar", revenue=383_000_000_000, net_income=97_000_000_000)
    fin = models.get_financials("AAPL", limit=5)
    assert len(fin) == 2 and fin[0]["fiscal_year"] == 2024, f"financials round-trip failed: {fin}"
    print(f"financials: 2 rows inserted, most recent first -> {[r['fiscal_year'] for r in fin]}")

    # --- daily prices ---
    n = models.upsert_daily_prices("AAPL", [
        {"date": "2024-01-02", "open": 187.0, "high": 188.0, "low": 183.0, "close": 185.6, "adj_close": 185.6, "volume": 80_000_000},
        {"date": "2024-01-03", "open": 184.2, "high": 185.9, "low": 183.4, "close": 184.3, "adj_close": 184.3, "volume": 70_000_000},
        {"date": "2024-01-04", "open": 182.1, "high": 183.1, "low": 180.9, "close": 181.9, "adj_close": 181.9, "volume": 65_000_000},
    ])
    assert n == 3
    prices = models.get_daily_prices("AAPL", start_date="2024-01-03")
    assert len(prices) == 2 and prices[0]["date"] == "2024-01-03"
    print(f"daily_prices: bulk upsert + filtered read OK ({n} written, {len(prices)} >= 2024-01-03)")

    # --- scores ---
    models.upsert_scores(
        "AAPL",
        graham_total=8, graham_max=10, graham_pct=0.8, graham_grade="B",
        graham_details=json.dumps({"earnings_stability": 1, "current_ratio": 1}),
        fisher_total=12, fisher_max=15, fisher_pct=0.8, fisher_grade="B",
        intrinsic_value_composite=210.0,
        discount_to_intrinsic=0.13,
        signal="BUY",
    )
    sc = models.get_scores("AAPL")
    assert sc and sc["graham_grade"] == "B" and sc["signal"] == "BUY"
    print(f"scores: upsert+get OK -> grade {sc['graham_grade']}, signal {sc['signal']}")

    # --- screener ---
    results = models.screen_companies(sector="Technology", min_graham_score=0.5, sort_by="graham_pct")
    assert len(results) == 1 and results[0]["symbol"] == "AAPL"
    print(f"screen_companies: filter+sort OK -> {results[0]['symbol']} (graham_pct={results[0]['graham_pct']})")

    none_results = models.screen_companies(sector="Healthcare")
    assert none_results == []
    print("screen_companies: empty filter result OK")

    # --- search ---
    found = models.search_companies("apple")
    assert any(r["symbol"] == "AAPL" for r in found)
    print(f"search_companies: name LIKE OK -> {[r['symbol'] for r in found]}")

    # --- stats ---
    stats = models.db_stats()
    assert stats["companies"] == 1 and stats["financials_rows"] == 2 and stats["daily_prices_rows"] == 3
    print(f"db_stats: {stats}")

    # cleanup
    db_mod.close_db()
    os.remove(test_path)
    wal = test_path + "-wal"
    shm = test_path + "-shm"
    for p in (wal, shm):
        if os.path.exists(p):
            os.remove(p)

    print("\nAll Step 1 checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
