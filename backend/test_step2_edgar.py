"""Sanity test for Step 2: SEC EDGAR fetch + parse.

Pulls Apple's full XBRL companyfacts, parses annual financials, and prints
the 5 most recent years' revenue + net income + a few balance-sheet items.

Run from backend/ with:  py test_step2_edgar.py
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from ingestion import edgar


def fmt_money(v):
    if v is None:
        return "None"
    if abs(v) >= 1e9:
        return f"${v / 1e9:>8.2f}B"
    if abs(v) >= 1e6:
        return f"${v / 1e6:>8.2f}M"
    return f"${v:>10.2f}"


def fmt_pct(v):
    if v is None:
        return "None"
    return f"{v * 100:>6.2f}%"


def main() -> int:
    print("=== CIK lookup ===")
    cik = edgar.get_cik("AAPL")
    print(f"AAPL -> CIK {cik}")
    assert cik == "0000320193", f"unexpected CIK for AAPL: {cik}"

    # Test a few more
    for t in ("MSFT", "KO", "JNJ", "WMT"):
        c = edgar.get_cik(t)
        print(f"{t:5s} -> CIK {c}")
        assert c is not None, f"no CIK for {t}"

    print("\n=== fetch + parse AAPL annual financials ===")
    records = edgar.fetch_annual_financials("AAPL")
    print(f"Got {len(records)} fiscal years\n")

    assert len(records) >= 5, f"expected >=5 years for AAPL, got {len(records)}"

    print(f"{'FY':>4} {'Date':>12} {'Revenue':>12} {'NetIncome':>12} {'Assets':>12} "
          f"{'Liab':>12} {'Equity':>12} {'Debt':>12} {'OpCF':>12} {'FCF':>12} "
          f"{'CR':>6} {'GM':>7} {'NM':>7} {'ROE':>7}")
    for r in records[:8]:
        print(
            f"{r['fiscal_year']:>4} "
            f"{str(r.get('fiscal_date') or ''):>12} "
            f"{fmt_money(r.get('revenue')):>12} "
            f"{fmt_money(r.get('net_income')):>12} "
            f"{fmt_money(r.get('total_assets')):>12} "
            f"{fmt_money(r.get('total_liabilities')):>12} "
            f"{fmt_money(r.get('total_stockholders_equity')):>12} "
            f"{fmt_money(r.get('total_debt')):>12} "
            f"{fmt_money(r.get('operating_cash_flow')):>12} "
            f"{fmt_money(r.get('free_cash_flow')):>12} "
            f"{(f'{r.get("current_ratio"):.2f}' if r.get('current_ratio') is not None else 'None'):>6} "
            f"{fmt_pct(r.get('gross_margin')):>7} "
            f"{fmt_pct(r.get('net_margin')):>7} "
            f"{fmt_pct(r.get('roe')):>7}"
        )

    # Spot checks on most recent year
    latest = records[0]
    assert latest.get("revenue") is not None and latest["revenue"] > 100e9, \
        f"AAPL latest revenue looks wrong: {latest.get('revenue')}"
    assert latest.get("net_income") is not None and latest["net_income"] > 50e9, \
        f"AAPL latest net income looks wrong: {latest.get('net_income')}"
    assert latest.get("total_assets") is not None and latest["total_assets"] > 200e9, \
        f"AAPL latest total assets looks wrong: {latest.get('total_assets')}"
    assert latest.get("gross_margin") is not None and 0.2 < latest["gross_margin"] < 0.6
    assert latest.get("source") == "edgar"
    print(f"\nLatest year sanity checks passed (FY {latest['fiscal_year']}).")

    # Coverage report: how often each field is present across all years
    print("\n=== field coverage across all returned years ===")
    field_keys = [
        "revenue", "cost_of_revenue", "gross_profit", "operating_income",
        "net_income", "eps", "eps_diluted",
        "total_assets", "total_current_assets",
        "total_liabilities", "total_current_liabilities",
        "total_stockholders_equity", "total_debt", "cash_and_equivalents",
        "operating_cash_flow", "capital_expenditure", "free_cash_flow",
        "dividends_paid", "research_and_development",
    ]
    for f in field_keys:
        n = sum(1 for r in records if r.get(f) is not None)
        print(f"  {f:35s} {n:>2}/{len(records)}")

    print("\nAll Step 2 checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
