"""
Backtesting Engine

Simulates a Graham-style value investing strategy over historical data.
Uses Graham's intrinsic value formula to generate buy/sell signals
based on margin of safety thresholds.
"""

from collections import defaultdict


def safe_div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def run_backtest(profile, income, historical_prices, margin_of_safety=0.35,
                 sell_premium=0.20, years=5):
    """
    Simulate a Graham value investing strategy.

    Args:
        profile: list with one profile dict
        income: list of annual income statements (most recent first)
        historical_prices: list of daily price records
        margin_of_safety: buy threshold (default 0.35 = 35% discount)
        sell_premium: sell threshold (default 0.20 = 20% premium)
        years: how many years to backtest

    Returns:
        dict with yearlyData, tradeLog, summary
    """
    if not profile or not income or not historical_prices:
        return {"error": "Insufficient data for backtesting"}

    prof = profile[0] if profile else {}
    symbol = prof.get("symbol", "UNKNOWN")

    # Build EPS by fiscal year
    eps_by_year = {}
    for stmt in income:
        date_str = stmt.get("date", "")
        fiscal_year = stmt.get("fiscalYear")
        eps = stmt.get("eps")

        if fiscal_year and eps is not None:
            eps_by_year[int(fiscal_year)] = eps
        elif date_str and eps is not None:
            try:
                yr = int(date_str[:4])
                eps_by_year[yr] = eps
            except (ValueError, IndexError):
                continue

    # Group daily prices by year
    prices_by_year = defaultdict(list)
    for record in historical_prices:
        date_str = record.get("date", "")
        close = record.get("close") or record.get("adjClose")
        if date_str and close:
            try:
                yr = int(date_str[:4])
                prices_by_year[yr].append(close)
            except (ValueError, IndexError):
                continue

    # Compute average price per year
    avg_prices = {}
    for yr, prices in prices_by_year.items():
        avg_prices[yr] = sum(prices) / len(prices)

    # Determine backtest range
    all_years = sorted(set(avg_prices.keys()) & set(eps_by_year.keys()))
    if not all_years:
        return {"error": "No overlapping years between price and earnings data"}

    end_year = max(all_years)
    start_year = max(end_year - years + 1, min(all_years))
    backtest_years = [y for y in all_years if start_year <= y <= end_year]

    if not backtest_years:
        return {"error": "No valid years for backtesting"}

    # Simulation
    starting_capital = 100_000
    cash = starting_capital
    shares_held = 0
    trade_log = []
    yearly_data = []

    for year in backtest_years:
        avg_price = avg_prices[year]
        eps = eps_by_year.get(year, 0)

        # Compute Graham intrinsic value using conservative 5% growth
        if eps and eps > 0:
            intrinsic = eps * (8.5 + 2 * 5.0) * 4.4 / 4.5
            discount = (intrinsic - avg_price) / intrinsic if intrinsic > 0 else 0
        else:
            intrinsic = None
            discount = None

        action = "HOLD"
        trade_shares = 0
        trade_price = avg_price

        if discount is not None:
            # BUY signal: discount exceeds margin of safety
            if discount > margin_of_safety and cash > 0:
                buy_amount = cash * 0.5  # Invest 50% of available cash
                trade_shares = int(buy_amount / avg_price)
                if trade_shares > 0:
                    cost = trade_shares * avg_price
                    cash -= cost
                    shares_held += trade_shares
                    action = "BUY"
                    trade_log.append({
                        "year": year,
                        "action": "BUY",
                        "shares": trade_shares,
                        "price": round(avg_price, 2),
                        "total": round(cost, 2),
                        "discount": round(discount * 100, 1),
                    })

            # SELL signal: stock is overvalued beyond sell premium
            elif discount < -sell_premium and shares_held > 0:
                sell_shares = max(1, shares_held // 2)  # Sell 50% of holdings
                proceeds = sell_shares * avg_price
                cash += proceeds
                shares_held -= sell_shares
                action = "SELL"
                trade_shares = sell_shares
                trade_log.append({
                    "year": year,
                    "action": "SELL",
                    "shares": sell_shares,
                    "price": round(avg_price, 2),
                    "total": round(proceeds, 2),
                    "discount": round(discount * 100, 1),
                })

        portfolio_value = cash + (shares_held * avg_price)

        yearly_data.append({
            "year": year,
            "avgPrice": round(avg_price, 2),
            "eps": round(eps, 2) if eps else None,
            "intrinsicValue": round(intrinsic, 2) if intrinsic is not None else None,
            "discount": round(discount * 100, 1) if discount is not None else None,
            "action": action,
            "sharesBought": trade_shares if action == "BUY" else 0,
            "sharesSold": trade_shares if action == "SELL" else 0,
            "sharesHeld": shares_held,
            "cash": round(cash, 2),
            "portfolioValue": round(portfolio_value, 2),
        })

    # Compute summary
    ending_value = yearly_data[-1]["portfolioValue"] if yearly_data else starting_capital
    total_return = (ending_value - starting_capital) / starting_capital * 100
    n_years = len(backtest_years)
    annualized_return = ((ending_value / starting_capital) ** (1 / n_years) - 1) * 100 if n_years > 0 else 0

    return {
        "symbol": symbol,
        "yearlyData": yearly_data,
        "tradeLog": trade_log,
        "summary": {
            "startingCapital": starting_capital,
            "endingValue": round(ending_value, 2),
            "totalReturn": round(total_return, 1),
            "annualizedReturn": round(annualized_return, 1),
            "yearsBacktested": n_years,
            "totalTrades": len(trade_log),
            "marginOfSafety": margin_of_safety,
            "sellPremium": sell_premium,
        },
    }
