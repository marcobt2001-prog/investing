"""Sanity test for Step 3: yfinance profile + price fetch.

Pulls Coca-Cola's profile, 1 year of daily prices, and a 2-symbol bulk
price fetch. Verifies shape and basic plausibility of the data.

Run from backend/ with:  py test_step3_yfinance.py
"""

import datetime as dt
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from ingestion import yfinance_fetcher as yfx


def fmt_money(v):
    if v is None:
        return "None"
    if abs(v) >= 1e9:
        return f"${v / 1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"${v / 1e6:.2f}M"
    return f"${v:.2f}"


def main() -> int:
    print("=== fetch KO profile ===")
    p = yfx.fetch_profile("KO")
    assert p is not None, "expected a profile dict for KO"
    print(f"  symbol:             {p['symbol']}")
    print(f"  name:               {p['name']}")
    print(f"  sector:             {p['sector']}")
    print(f"  industry:           {p['industry']}")
    print(f"  exchange:           {p['exchange']}")
    print(f"  market_cap:         {fmt_money(p['market_cap'])}")
    print(f"  price:              {fmt_money(p['price'])}")
    print(f"  shares_outstanding: {p['shares_outstanding']:,}" if p['shares_outstanding'] else "  shares_outstanding: None")
    print(f"  beta:               {p['beta']}")
    print(f"  dividend_yield:     {p['dividend_yield']}")
    desc = (p.get("description") or "")
    print(f"  description:        {desc[:120]}{'...' if len(desc) > 120 else ''}")

    assert p["symbol"] == "KO"
    assert p["name"] and "coca" in p["name"].lower()
    assert p["price"] is not None and 30 < p["price"] < 200, f"KO price implausible: {p['price']}"
    assert p["market_cap"] is not None and p["market_cap"] > 100e9, "KO market cap should be >$100B"
    assert p["sector"] is not None
    print("  -> KO profile sanity checks passed")

    print("\n=== fetch 1y of KO daily prices ===")
    end = dt.date.today().isoformat()
    start = (dt.date.today() - dt.timedelta(days=365)).isoformat()
    rows = yfx.fetch_daily_prices("KO", start=start, end=end)
    print(f"  got {len(rows)} bars between {start} and {end}")
    # ~252 trading days/year, give a wide tolerance
    assert 200 <= len(rows) <= 280, f"unexpected bar count for 1y of KO: {len(rows)}"
    first, last = rows[0], rows[-1]
    print(f"  first bar: {first['date']}  O={first['open']:.2f} H={first['high']:.2f} L={first['low']:.2f} C={first['close']:.2f} V={first['volume']:,}")
    print(f"  last  bar: {last['date']}   O={last['open']:.2f} H={last['high']:.2f} L={last['low']:.2f} C={last['close']:.2f} V={last['volume']:,}")
    for r in rows:
        assert r["symbol"] == "KO"
        assert r["close"] is not None and r["close"] > 0
        assert r["volume"] >= 0
    print("  -> KO price sanity checks passed")

    print("\n=== bulk fetch (KO + JNJ), last 90 days ===")
    bulk_start = (dt.date.today() - dt.timedelta(days=90)).isoformat()
    bulk = yfx.fetch_daily_prices_bulk(["KO", "JNJ"], start=bulk_start, end=end)
    for sym, srows in bulk.items():
        print(f"  {sym}: {len(srows)} bars (first={srows[0]['date'] if srows else 'n/a'}, last={srows[-1]['date'] if srows else 'n/a'})")
    assert len(bulk["KO"]) > 50 and len(bulk["JNJ"]) > 50

    print("\nAll Step 3 checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
