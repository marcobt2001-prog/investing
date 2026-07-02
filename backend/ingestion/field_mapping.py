"""XBRL tag -> normalized field name mapping.

Companies report the same concept under different US-GAAP tags. We pick the
first available tag for each field; the parser also tracks which tag it
matched so we can later expand coverage for outliers.

The mapping is many-to-one: e.g. revenue can come from `Revenues`,
`RevenueFromContractWithCustomerExcludingAssessedTax`, `SalesRevenueNet`, etc.
"""

# Direct tag -> field mapping. Order doesn't matter at lookup time, but the
# parser walks fields in FIELD_PRIORITY order and picks the first tag with data.
XBRL_TO_FIELD: dict[str, str] = {
    # Revenue
    "Revenues": "revenue",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "RevenueFromContractWithCustomerIncludingAssessedTax": "revenue",
    "SalesRevenueNet": "revenue",
    "SalesRevenueGoodsNet": "revenue",

    # Cost of Revenue
    "CostOfRevenue": "cost_of_revenue",
    "CostOfGoodsAndServicesSold": "cost_of_revenue",
    "CostOfGoodsSold": "cost_of_revenue",

    # Gross Profit (sometimes reported directly)
    "GrossProfit": "gross_profit",

    # Operating Income
    "OperatingIncomeLoss": "operating_income",

    # Net Income
    "NetIncomeLoss": "net_income",
    "ProfitLoss": "net_income",
    "NetIncomeLossAvailableToCommonStockholdersBasic": "net_income",

    # EPS
    "EarningsPerShareBasic": "eps",
    "EarningsPerShareDiluted": "eps_diluted",

    # R&D / SGA
    "ResearchAndDevelopmentExpense": "research_and_development",
    "SellingGeneralAndAdministrativeExpense": "sga_expense",

    # Shares Outstanding
    "WeightedAverageNumberOfSharesOutstandingBasic": "weighted_avg_shares",
    "WeightedAverageNumberOfShareOutstandingBasicAndDiluted": "weighted_avg_shares",
    "CommonStockSharesOutstanding": "weighted_avg_shares",
    "WeightedAverageNumberOfDilutedSharesOutstanding": "weighted_avg_shares_diluted",

    # Balance Sheet
    "Assets": "total_assets",
    "AssetsCurrent": "total_current_assets",
    "Liabilities": "total_liabilities",
    "LiabilitiesCurrent": "total_current_liabilities",
    "StockholdersEquity": "total_stockholders_equity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": "total_stockholders_equity",
    "RetainedEarningsAccumulatedDeficit": "retained_earnings",
    "CashAndCashEquivalentsAtCarryingValue": "cash_and_equivalents",
    "Cash": "cash_and_equivalents",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents": "cash_and_equivalents",

    # Debt — handled specially in parser (sum long-term + current)
    "LongTermDebt": "long_term_debt",
    "LongTermDebtNoncurrent": "long_term_debt",
    "LongTermDebtAndCapitalLeaseObligations": "long_term_debt",
    "DebtCurrent": "short_term_debt",
    "LongTermDebtCurrent": "short_term_debt",
    "ShortTermBorrowings": "short_term_debt",

    # Cash Flow
    "NetCashProvidedByUsedInOperatingActivities": "operating_cash_flow",
    "PaymentsToAcquirePropertyPlantAndEquipment": "capital_expenditure",
    "PaymentsForCapitalImprovements": "capital_expenditure",
    "PaymentsOfDividends": "dividends_paid",
    "PaymentsOfDividendsCommonStock": "dividends_paid",
}


# Priority order: when multiple XBRL tags map to the same field, prefer the
# first one in this list that has data for the given fiscal year. Tags not
# listed here fall back to dictionary-iteration order.
FIELD_PRIORITY: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ],
    "cost_of_revenue": [
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
    ],
    "net_income": [
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ],
    "weighted_avg_shares": [
        "WeightedAverageNumberOfSharesOutstandingBasic",
        "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
        "CommonStockSharesOutstanding",
    ],
    "long_term_debt": [
        "LongTermDebtNoncurrent",
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligations",
    ],
    "short_term_debt": [
        "DebtCurrent",
        "LongTermDebtCurrent",
        "ShortTermBorrowings",
    ],
    "cash_and_equivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
        "Cash",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "total_stockholders_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "dividends_paid": [
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStock",
    ],
    "capital_expenditure": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForCapitalImprovements",
    ],
}


def tags_for_field(field: str) -> list[str]:
    """Return the prioritized list of XBRL tags that map to a given field."""
    if field in FIELD_PRIORITY:
        # Start with prioritized tags, then append any other tags that map to
        # this field but weren't explicitly prioritized.
        prioritized = FIELD_PRIORITY[field]
        extras = [t for t, f in XBRL_TO_FIELD.items() if f == field and t not in prioritized]
        return prioritized + extras
    return [t for t, f in XBRL_TO_FIELD.items() if f == field]
