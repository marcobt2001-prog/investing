"""
Graham Scoring Engine

Scores stocks against Benjamin Graham's criteria from The Intelligent Investor.
Each criterion scores 0, 0.5, or 1.0. Total is graded A/B/C/D.
"""


def safe_div(a, b):
    """Safe division returning None if b is zero or either value is None."""
    if a is None or b is None or b == 0:
        return None
    return a / b


def score_graham(profile, income, balance, cashflow, key_metrics):
    """
    Run Graham analysis on a stock.

    Args:
        profile: list with one profile dict (from FMP /profile)
        income: list of annual income statements (most recent first)
        balance: list of annual balance sheets (most recent first)
        cashflow: list of annual cash flow statements (most recent first)
        key_metrics: list of annual key metrics (most recent first)

    Returns:
        dict with scores, details, totalScore, maxScore, pctScore, grade
    """
    scores = {}
    details = {}

    prof = profile[0] if profile else {}
    latest_income = income[0] if income else {}
    latest_balance = balance[0] if balance else {}
    price = prof.get("price")
    shares = None

    # Try to get shares outstanding from key_metrics or profile
    if key_metrics and key_metrics[0].get("marketCap") and price and price > 0:
        shares = key_metrics[0]["marketCap"] / price
    elif prof.get("marketCap") and price and price > 0:
        shares = prof["marketCap"] / price

    # 1. Adequate Size (Revenue > $100M)
    revenue = latest_income.get("revenue")
    if revenue is not None:
        if revenue > 100_000_000:
            scores["adequateSize"] = 1.0
        elif revenue > 50_000_000:
            scores["adequateSize"] = 0.5
        else:
            scores["adequateSize"] = 0
    else:
        scores["adequateSize"] = 0
    details["adequateSize"] = {
        "label": "Adequate Size (Revenue)",
        "value": revenue,
        "threshold": "> $100M (full), > $50M (half)",
    }

    # 2. Current Ratio (Current Assets / Current Liabilities >= 2.0)
    current_assets = latest_balance.get("totalCurrentAssets")
    current_liabilities = latest_balance.get("totalCurrentLiabilities")
    current_ratio = safe_div(current_assets, current_liabilities)
    if current_ratio is not None:
        if current_ratio >= 2.0:
            scores["currentRatio"] = 1.0
        elif current_ratio >= 1.5:
            scores["currentRatio"] = 0.5
        else:
            scores["currentRatio"] = 0
    else:
        scores["currentRatio"] = 0
    details["currentRatio"] = {
        "label": "Current Ratio",
        "value": round(current_ratio, 2) if current_ratio is not None else None,
        "threshold": ">= 2.0 (full), >= 1.5 (half)",
    }

    # 3. Debt to Equity (Total Debt / Total Stockholders Equity < 0.5)
    total_debt = latest_balance.get("totalDebt")
    equity = latest_balance.get("totalStockholdersEquity")
    de_ratio = safe_div(total_debt, equity)
    if de_ratio is not None and equity and equity > 0:
        if de_ratio < 0.5:
            scores["debtToEquity"] = 1.0
        elif de_ratio < 1.0:
            scores["debtToEquity"] = 0.5
        else:
            scores["debtToEquity"] = 0
    else:
        scores["debtToEquity"] = 0
    details["debtToEquity"] = {
        "label": "Debt to Equity",
        "value": round(de_ratio, 2) if de_ratio is not None else None,
        "threshold": "< 0.5 (full), < 1.0 (half)",
    }

    # 4. Earnings Stability (Positive net income over available years)
    positive_years = 0
    total_years = len(income)
    for stmt in income:
        ni = stmt.get("netIncome")
        if ni is not None and ni > 0:
            positive_years += 1
    stability_ratio = safe_div(positive_years, total_years) if total_years > 0 else 0
    if total_years >= 5 and positive_years == total_years:
        scores["earningsStability"] = 1.0
    elif total_years >= 3 and stability_ratio and stability_ratio >= 0.7:
        scores["earningsStability"] = 0.5
    else:
        scores["earningsStability"] = 0
    details["earningsStability"] = {
        "label": "Earnings Stability",
        "value": f"{positive_years}/{total_years} years positive",
        "threshold": "All years positive (full), 70%+ (half)",
    }

    # 5. Earnings Growth (compare recent avg vs older avg)
    # With 5 years of data: compare most recent 2yr avg vs oldest 2yr avg
    if len(income) >= 4:
        recent_eps = [s.get("eps", 0) or 0 for s in income[:2]]
        old_eps = [s.get("eps", 0) or 0 for s in income[-2:]]
        avg_recent = sum(recent_eps) / len(recent_eps) if recent_eps else 0
        avg_old = sum(old_eps) / len(old_eps) if old_eps else 0

        if avg_old > 0:
            growth = (avg_recent - avg_old) / avg_old
        else:
            growth = None

        if growth is not None:
            if growth > 0.33:
                scores["earningsGrowth"] = 1.0
            elif growth > 0.15:
                scores["earningsGrowth"] = 0.5
            else:
                scores["earningsGrowth"] = 0
        else:
            scores["earningsGrowth"] = 0
        details["earningsGrowth"] = {
            "label": "Earnings Growth",
            "value": f"{growth * 100:.1f}%" if growth is not None else "N/A",
            "threshold": "> 33% (full), > 15% (half)",
        }
    else:
        scores["earningsGrowth"] = 0
        details["earningsGrowth"] = {
            "label": "Earnings Growth",
            "value": "Insufficient data",
            "threshold": "> 33% (full), > 15% (half)",
        }

    # 6. Moderate P/E (Price / EPS < 15)
    eps = latest_income.get("eps")
    pe = safe_div(price, eps) if price and eps and eps > 0 else None
    if pe is not None:
        if pe < 15:
            scores["moderatePE"] = 1.0
        elif pe < 20:
            scores["moderatePE"] = 0.5
        else:
            scores["moderatePE"] = 0
    else:
        scores["moderatePE"] = 0
    details["moderatePE"] = {
        "label": "Moderate P/E Ratio",
        "value": round(pe, 2) if pe is not None else "N/A (negative earnings)",
        "threshold": "< 15 (full), < 20 (half)",
    }

    # 7. Moderate P/B (Price / Book Value per share)
    book_value = latest_balance.get("totalStockholdersEquity")
    bvps = safe_div(book_value, shares) if shares else None
    pb = safe_div(price, bvps) if price and bvps and bvps > 0 else None
    pe_pb_product = (pe * pb) if pe is not None and pb is not None else None

    if pb is not None:
        if pb < 1.5:
            scores["moderatePB"] = 1.0
        elif pe_pb_product is not None and pe_pb_product < 22.5:
            scores["moderatePB"] = 1.0
        elif pb < 2.5:
            scores["moderatePB"] = 0.5
        else:
            scores["moderatePB"] = 0
    else:
        scores["moderatePB"] = 0
    details["moderatePB"] = {
        "label": "Moderate P/B Ratio",
        "value": round(pb, 2) if pb is not None else "N/A",
        "threshold": "< 1.5 or P/E×P/B < 22.5 (full), < 2.5 (half)",
        "pePbProduct": round(pe_pb_product, 2) if pe_pb_product is not None else None,
    }

    # 8. Dividend Record (paid dividends in last 5 years)
    div_years = 0
    div_total = min(len(cashflow), 5)
    for stmt in cashflow[:5]:
        # FMP stable API uses commonDividendsPaid (negative when dividends are paid)
        div_paid = stmt.get("commonDividendsPaid") or stmt.get("dividendsPaid") or stmt.get("netDividendsPaid")
        if div_paid is not None and div_paid < 0:
            div_years += 1
    if div_total >= 5 and div_years == 5:
        scores["dividendRecord"] = 1.0
    elif div_years >= 3:
        scores["dividendRecord"] = 0.5
    else:
        scores["dividendRecord"] = 0
    details["dividendRecord"] = {
        "label": "Dividend Record",
        "value": f"{div_years}/{div_total} years paid",
        "threshold": "5/5 years (full), 3+ years (half)",
    }

    # 9. NCAV (Net-Net): (Current Assets - Total Liabilities) / Shares Outstanding
    total_liabilities = latest_balance.get("totalLiabilities")
    if current_assets is not None and total_liabilities is not None and shares and shares > 0:
        ncav_per_share = (current_assets - total_liabilities) / shares
        price_to_ncav = safe_div(price, ncav_per_share) if price and ncav_per_share and ncav_per_share > 0 else None
        if price_to_ncav is not None:
            if price_to_ncav < 1.0:
                scores["ncav"] = 1.0
            elif price_to_ncav < 1.5:
                scores["ncav"] = 0.5
            else:
                scores["ncav"] = 0
        else:
            scores["ncav"] = 0
    else:
        ncav_per_share = None
        price_to_ncav = None
        scores["ncav"] = 0
    details["ncav"] = {
        "label": "NCAV (Net-Net)",
        "value": round(ncav_per_share, 2) if ncav_per_share is not None else "N/A",
        "priceToNcav": round(price_to_ncav, 2) if price_to_ncav is not None else "N/A",
        "threshold": "Price/NCAV < 1.0 (full), < 1.5 (half)",
    }

    # Compute totals and grade
    total_score = sum(scores.values())
    max_score = len(scores)
    pct_score = safe_div(total_score, max_score) if max_score > 0 else 0

    if pct_score >= 0.80:
        grade = "A"
    elif pct_score >= 0.60:
        grade = "B"
    elif pct_score >= 0.40:
        grade = "C"
    else:
        grade = "D"

    return {
        "scores": scores,
        "details": details,
        "totalScore": total_score,
        "maxScore": max_score,
        "pctScore": round(pct_score, 3) if pct_score else 0,
        "grade": grade,
    }
