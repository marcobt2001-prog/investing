"""Sanity test for Step 4: end-to-end ingestion of 5 companies.

Pulls profile + EDGAR financials + prices for AAPL/KO/JNJ/PG/WMT, runs
Graham/Fisher/valuation, and verifies every table is populated.

Run from backend/ with:  py test_step4_bulk_ingest.py

This test uses a throwaway DB so it doesn't pollute the real one.
"""

import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("yfinance").setLevel(logging.ERROR)

from database import db as db_mod
from database import models
from ingestion import bulk_ingest


def main() -> int:
    test_path = os.path.join(os.path.dirname(db_mod.DB_PATH), "test_step4.db")
    for p in (test_path, test_path + "-wal", test_path + "-shm"):
        if os.path.exists(p):
            os.remove(p)
    db_mod.DB_PATH = test_path
    db_mod.close_db()
    db_mod.init_db()
    print(f"Using throwaway DB: {test_path}")

    tickers = ["AAPL", "KO", "JNJ", "PG", "WMT"]
    print(f"\n=== bulk_ingest({tickers}) ===")
    t0 = time.monotonic()
    results = bulk_ingest.bulk_ingest(tickers, skip_existing=False, sleep_between=0.3)
    elapsed = time.monotonic() - t0
    print(f"\nTotal elapsed: {elapsed:.1f}s")

    failures = [r for r in results if not r.get("ok")]
    if failures:
        print("\nFAILURES:")
        for r in failures:
            print(f"  {r['symbol']}: {r['errors']}")
        return 1

    print("\n=== per-ticker verification ===")
    print(f"{'SYM':<5} {'NAME':<28} {'SECTOR':<22} {'PRICE':>8} {'#FIN':>5} {'#PRC':>6} "
          f"{'GRAHAM':>10} {'FISHER':>10} {'COMPOSITE':>10} {'SIGNAL':<14}")
    for sym in tickers:
        company = models.get_company(sym)
        assert company is not None, f"no company row for {sym}"
        assert company.get("name"), f"no name for {sym}"
        assert company.get("price"), f"no price for {sym}"
        assert company.get("sector"), f"no sector for {sym}"
        assert company.get("cik"), f"no CIK for {sym}"

        fin = models.get_financials(sym, limit=20)
        assert len(fin) >= 5, f"{sym} has only {len(fin)} years of financials"

        prices = models.get_daily_prices(sym)
        assert len(prices) > 100, f"{sym} has only {len(prices)} price bars"

        scores = models.get_scores(sym)
        assert scores is not None, f"no scores for {sym}"
        assert scores.get("graham_grade") in {"A", "B", "C", "D"}, f"invalid graham_grade for {sym}"
        assert scores.get("fisher_grade") in {"A", "B", "C", "D"}, f"invalid fisher_grade for {sym}"
        # signal can be None if no positive intrinsic was computed, but for
        # these blue chips we expect one
        assert scores.get("signal"), f"no signal for {sym}"
        assert scores.get("intrinsic_value_composite"), f"no composite IV for {sym}"

        print(
            f"{sym:<5} "
            f"{(company['name'] or '')[:27]:<28} "
            f"{(company['sector'] or '')[:21]:<22} "
            f"${company['price']:>7.2f} "
            f"{len(fin):>5} "
            f"{len(prices):>6} "
            f"{scores['graham_grade']} ({scores['graham_pct']:.2f})  "
            f"{scores['fisher_grade']} ({scores['fisher_pct']:.2f})  "
            f"${scores['intrinsic_value_composite']:>8.2f} "
            f"{scores['signal']:<14}"
        )

    print("\n=== screen_companies smoke test ===")
    all_rows = models.screen_companies(limit=20)
    print(f"all (no filter, sort by graham_pct DESC): {len(all_rows)} rows")
    for r in all_rows:
        print(f"  {r['symbol']:<5} {r['graham_grade']}  fisher={r['fisher_grade']}  "
              f"signal={r['signal']:<14}  composite=${r['intrinsic_value_composite']:.2f}")

    cd = models.screen_companies(sector="Consumer Defensive", limit=10)
    print(f"\nfiltered (sector=Consumer Defensive): {[r['symbol'] for r in cd]}")
    assert {"KO", "PG", "WMT"}.issubset({r["symbol"] for r in cd})

    print("\n=== db_stats ===")
    print(models.db_stats())

    print("\n=== refresh_scores re-runs cleanly ===")
    n = bulk_ingest.refresh_scores(tickers)
    assert n == len(tickers), f"refresh_scores rebuilt {n}/{len(tickers)}"
    print(f"refresh_scores rebuilt {n}/{len(tickers)}")

    # cleanup
    db_mod.close_db()
    for p in (test_path, test_path + "-wal", test_path + "-shm"):
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass

    print("\nAll Step 4 checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
