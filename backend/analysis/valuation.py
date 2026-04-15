"""
Valuation Models

Computes 5 intrinsic value models and a composite buy/sell signal:
1. Graham's Intrinsic Value Formula
2. Simplified DCF (10-year)
3. Book Value (Net Asset Value)
4. Earnings Power Value (EPV)
5. NCAV (Net-Net)
"""


def safe_div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def graham_formula(income, profile, aaa_yield=4.5):
    """
    Graham's Intrinsic Value: V = EPS × (8.5 + 2g) × 4.4 / Y
    g = EPS growth rate (capped at 15%)
    Y = AAA corporate bond yield
    """
    if not income or len(income) < 2:
        return None

    latest_eps = income[0].get("eps")
    if not latest_eps or latest_eps <= 0:
        return None

    # Compute EPS growth rate from available data
    oldest_eps = income[-1].get("eps")
    years = len(income) - 1

    if oldest_eps and oldest_eps > 0 and years > 0:
        growth = ((latest_eps / oldest_eps) ** (1 / years) - 1) * 100
    else:
        growth = 5.0  # Conservative default

    growth = min(growth, 15.0)  # Cap at 15%
    growth = max(growth, 0)

    value = latest_eps * (8.5 + 2 * growth) * 4.4 / aaa_yield
    return {
        "intrinsicValue": round(value, 2),
        "label": "Graham Formula",
        "description": f"V = EPS × (8.5 + 2g) × 4.4 / Y",
        "inputs": {
            "eps": round(latest_eps, 2),
            "growthRate": round(growth, 1),
            "aaaYield": aaa_yield,
        },
    }


def simplified_dcf(cashflow, profile, wacc=10.0, terminal_growth=2.5):
    """
    Simplified 10-year DCF model.
    Projects FCF growth, discounts at WACC, adds terminal value.
    """
    if not cashflow or len(cashflow) < 2:
        return None

    prof = profile[0] if profile else {}
    price = prof.get("price")
    market_cap = prof.get("marketCap")
    shares = safe_div(market_cap, price) if market_cap and price and price > 0 else None
    if not shares:
        return None

    # Get most recent FCF
    latest_fcf = cashflow[0].get("freeCashFlow")
    if not latest_fcf or latest_fcf <= 0:
        return None

    # Compute FCF growth rate
    oldest_fcf = cashflow[-1].get("freeCashFlow")
    years = len(cashflow) - 1

    if oldest_fcf and oldest_fcf > 0 and years > 0:
        fcf_growth = ((latest_fcf / oldest_fcf) ** (1 / years) - 1)
    else:
        fcf_growth = 0.05  # 5% default

    fcf_growth = min(fcf_growth, 0.15)  # Cap at 15%
    fcf_growth = max(fcf_growth, 0)

    wacc_decimal = wacc / 100
    tg_decimal = terminal_growth / 100

    # Project 10 years of FCF
    total_pv = 0
    projected_fcf = latest_fcf
    for year in range(1, 11):
        projected_fcf *= (1 + fcf_growth)
        pv = projected_fcf / ((1 + wacc_decimal) ** year)
        total_pv += pv

    # Terminal value (perpetuity growth)
    terminal_fcf = projected_fcf * (1 + tg_decimal)
    terminal_value = terminal_fcf / (wacc_decimal - tg_decimal)
    pv_terminal = terminal_value / ((1 + wacc_decimal) ** 10)

    enterprise_value = total_pv + pv_terminal
    per_share = enterprise_value / shares

    return {
        "intrinsicValue": round(per_share, 2),
        "label": "DCF (10-Year)",
        "description": "Discounted Cash Flow with terminal value",
        "inputs": {
            "latestFCF": round(latest_fcf / 1e6, 1),
            "fcfGrowth": round(fcf_growth * 100, 1),
            "wacc": wacc,
            "terminalGrowth": terminal_growth,
        },
    }


def book_value(balance, profile):
    """
    Book Value per share = Total Stockholders' Equity / Shares Outstanding
    """
    if not balance or not profile:
        return None

    prof = profile[0] if profile else {}
    latest = balance[0] if balance else {}

    equity = latest.get("totalStockholdersEquity")
    price = prof.get("price")
    market_cap = prof.get("marketCap")
    shares = safe_div(market_cap, price) if market_cap and price and price > 0 else None

    if equity is None or not shares:
        return None

    bv_per_share = equity / shares

    return {
        "intrinsicValue": round(bv_per_share, 2),
        "label": "Book Value",
        "description": "Total Equity / Shares Outstanding",
        "inputs": {
            "totalEquity": round(equity / 1e6, 1),
            "shares": round(shares / 1e6, 1),
        },
    }


def earnings_power_value(income, profile, cost_of_capital=10.0):
    """
    EPV = Average Net Income / Cost of Capital, per share.
    """
    if not income or not profile:
        return None

    prof = profile[0] if profile else {}
    price = prof.get("price")
    market_cap = prof.get("marketCap")
    shares = safe_div(market_cap, price) if market_cap and price and price > 0 else None

    if not shares:
        return None

    # Average net income over available years
    net_incomes = [s.get("netIncome") for s in income if s.get("netIncome") is not None]
    if not net_incomes:
        return None

    avg_ni = sum(net_incomes) / len(net_incomes)
    if avg_ni <= 0:
        return None

    epv_total = avg_ni / (cost_of_capital / 100)
    per_share = epv_total / shares

    return {
        "intrinsicValue": round(per_share, 2),
        "label": "Earnings Power Value",
        "description": "Avg Net Income / Cost of Capital",
        "inputs": {
            "avgNetIncome": round(avg_ni / 1e6, 1),
            "costOfCapital": cost_of_capital,
            "yearsAveraged": len(net_incomes),
        },
    }


def ncav_value(balance, profile):
    """
    NCAV = (Total Current Assets - Total Liabilities) / Shares Outstanding
    Most conservative measure.
    """
    if not balance or not profile:
        return None

    prof = profile[0] if profile else {}
    latest = balance[0] if balance else {}

    current_assets = latest.get("totalCurrentAssets")
    total_liabilities = latest.get("totalLiabilities")
    price = prof.get("price")
    market_cap = prof.get("marketCap")
    shares = safe_div(market_cap, price) if market_cap and price and price > 0 else None

    if current_assets is None or total_liabilities is None or not shares:
        return None

    ncav = (current_assets - total_liabilities) / shares

    return {
        "intrinsicValue": round(ncav, 2),
        "label": "NCAV (Net-Net)",
        "description": "(Current Assets - Total Liabilities) / Shares",
        "inputs": {
            "currentAssets": round(current_assets / 1e6, 1),
            "totalLiabilities": round(total_liabilities / 1e6, 1),
        },
    }


def compute_valuations(profile, income, balance, cashflow, aaa_yield=4.5, wacc=10.0):
    """
    Run all 5 valuation models and compute composite value + buy/sell signal.

    Returns dict with models, compositeValue, signal, and buyPrices.
    """
    prof = profile[0] if profile else {}
    price = prof.get("price")

    models = {}

    # Run each model
    g = graham_formula(income, profile, aaa_yield)
    if g:
        models["graham"] = g

    d = simplified_dcf(cashflow, profile, wacc)
    if d:
        models["dcf"] = d

    b = book_value(balance, profile)
    if b:
        models["bookValue"] = b

    e = earnings_power_value(income, profile)
    if e:
        models["epv"] = e

    n = ncav_value(balance, profile)
    if n:
        models["ncav"] = n

    # Composite: average of all models that produce a positive value
    positive_values = [m["intrinsicValue"] for m in models.values() if m["intrinsicValue"] > 0]
    composite = sum(positive_values) / len(positive_values) if positive_values else None

    # Compute discount/premium for each model
    for key, model in models.items():
        iv = model["intrinsicValue"]
        if price and price > 0 and iv:
            discount = (iv - price) / iv if iv > 0 else None
            model["discount"] = round(discount * 100, 1) if discount is not None else None
        else:
            model["discount"] = None

    # Buy/Sell Signal based on composite
    signal = None
    composite_discount = None
    if composite and price and price > 0:
        composite_discount = (composite - price) / composite * 100

        if composite_discount > 35:
            signal = "STRONG BUY"
        elif composite_discount > 20:
            signal = "BUY"
        elif composite_discount > 0:
            signal = "HOLD"
        elif composite_discount > -20:
            signal = "OVERVALUED"
        else:
            signal = "STRONG SELL"

    # Buy prices at different margins of safety
    buy_prices = None
    if composite:
        buy_prices = {
            "mos25": round(composite * 0.75, 2),
            "mos35": round(composite * 0.65, 2),
            "mos50": round(composite * 0.50, 2),
        }

    return {
        "models": models,
        "compositeValue": round(composite, 2) if composite else None,
        "compositeDiscount": round(composite_discount, 1) if composite_discount is not None else None,
        "signal": signal,
        "currentPrice": price,
        "buyPrices": buy_prices,
    }
