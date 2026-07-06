"""Evaluation prompts.

SYSTEM_PROMPT establishes the analyst role and the JSON-only output contract.
build_evaluation_prompt() renders the company's data into a human-readable
prompt (readable numbers work better than raw integers) and appends the exact
JSON schema the model must return.
"""


SYSTEM_PROMPT = """You are a senior equity research analyst specializing in
fundamental analysis. You evaluate companies based on their financial statements
using established analytical frameworks.

Your role is NOT to recommend buying or selling. Your role is to identify:
- Competitive strengths and weaknesses
- Business risks and durability
- Earnings quality and sustainability
- Capital allocation effectiveness
- Key factors that would affect the company's intrinsic value going forward

You must respond ONLY with valid JSON matching the exact schema provided.
No markdown, no commentary outside the JSON structure. Every field must be
present. Scores are integers from 1 to 5 (1 = very poor/high risk,
5 = excellent/low risk)."""


def _fmt_large(n) -> str:
    """Format large numbers readably ($2.3B not 2300000000)."""
    if n is None:
        return "N/A"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "N/A"
    sign = "-" if n < 0 else ""
    a = abs(n)
    if a >= 1e9:
        return f"{sign}${a / 1e9:.1f}B"
    if a >= 1e6:
        return f"{sign}${a / 1e6:.1f}M"
    if a >= 1e3:
        return f"{sign}${a / 1e3:.0f}K"
    return f"{sign}${a:.0f}"


def _build_financial_table(financials: list[dict]) -> str:
    """Format financials as a readable aligned text table for the LLM."""
    if not financials:
        return "No financial data available."

    headers = ["Year", "Revenue", "Net Income", "Oper Income", "FCF",
               "Total Assets", "Total Debt", "Equity", "EPS",
               "Gross Margin", "Oper Margin", "ROE", "D/E"]

    def _pct(v):
        try:
            return f"{float(v) * 100:.1f}%"
        except (TypeError, ValueError):
            return "N/A"

    def _eps(v):
        try:
            return f"${float(v):.2f}"
        except (TypeError, ValueError):
            return "N/A"

    def _num(v):
        try:
            return f"{float(v):.2f}"
        except (TypeError, ValueError):
            return "N/A"

    rows = []
    for f in financials:
        rows.append([
            str(f.get("fiscal_year", "?")),
            _fmt_large(f.get("revenue")),
            _fmt_large(f.get("net_income")),
            _fmt_large(f.get("operating_income")),
            _fmt_large(f.get("free_cash_flow")),
            _fmt_large(f.get("total_assets")),
            _fmt_large(f.get("total_debt")),
            _fmt_large(f.get("total_stockholders_equity")),
            _eps(f.get("eps")),
            _pct(f.get("gross_margin")),
            _pct(f.get("operating_margin")),
            _pct(f.get("roe")),
            _num(f.get("debt_to_equity")),
        ])

    col_widths = [max(len(headers[i]), max(len(r[i]) for r in rows)) for i in range(len(headers))]
    header_line = " | ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    separator = "-+-".join("-" * w for w in col_widths)
    data_lines = [" | ".join(c.ljust(w) for c, w in zip(row, col_widths)) for row in rows]
    return "\n".join([header_line, separator] + data_lines)


def build_evaluation_prompt(company: dict, financials: list[dict],
                            graham_scores: dict, fisher_scores: dict,
                            valuation: dict) -> str:
    """Build the user prompt with all financial data, context, and the schema."""
    fin_table = _build_financial_table(financials[:5])

    price = company.get("price")
    price_str = f"${price:.2f}" if isinstance(price, (int, float)) else "N/A"
    graham_pct = (graham_scores.get("pctScore") or 0) * 100
    fisher_pct = (fisher_scores.get("pctScore") or 0) * 100
    composite = valuation.get("compositeValue")
    composite_str = f"${composite:.2f}" if isinstance(composite, (int, float)) else "N/A"
    disc = (valuation.get("compositeDiscount") or 0) * 100

    prompt = f"""Evaluate the following company based on its financial data.

## Company Profile
- Name: {company.get('name', 'Unknown')}
- Ticker: {company.get('symbol', 'Unknown')}
- Sector: {company.get('sector', 'Unknown')}
- Industry: {company.get('industry', 'Unknown')}
- Market Cap: {_fmt_large(company.get('market_cap'))}
- Current Price: {price_str}

## Financial Data (Last 5 Years, Most Recent First)
{fin_table}

## Quantitative Scores (Already Computed)
- Graham Score: {graham_scores.get('grade', 'N/A')} ({graham_pct:.0f}%)
- Fisher Score: {fisher_scores.get('grade', 'N/A')} ({fisher_pct:.0f}%)
- Composite Intrinsic Value: {composite_str}
- Current Signal: {valuation.get('signal', 'N/A')}
- Discount to Intrinsic Value: {disc:.1f}%

## Your Evaluation

Analyze this company across the following dimensions and respond with ONLY
this JSON structure (no other text):

{{
    "competitivePosition": {{
        "score": <1-5>,
        "moatType": "<one of: none, cost_advantage, switching_costs, network_effects, intangible_assets, efficient_scale, or multiple>",
        "moatDurability": "<one of: none, weak, moderate, strong>",
        "summary": "<2-3 sentences on competitive dynamics, market position, barriers to entry>"
    }},
    "earningsQuality": {{
        "score": <1-5>,
        "cashFlowAlignment": "<one of: strong, moderate, weak>",
        "revenueConcentration": "<one of: low, moderate, high>",
        "redFlags": ["<list any accounting concerns, if none use empty list>"],
        "summary": "<2-3 sentences on earnings sustainability and quality>"
    }},
    "capitalAllocation": {{
        "score": <1-5>,
        "reinvestmentQuality": "<one of: excellent, good, fair, poor>",
        "acquisitionTrackRecord": "<one of: value_creating, neutral, value_destroying, not_applicable>",
        "shareholderReturns": "<one of: excellent, good, fair, poor>",
        "debtManagement": "<one of: conservative, moderate, aggressive, overleveraged>",
        "summary": "<2-3 sentences on how management deploys capital>"
    }},
    "growthOutlook": {{
        "score": <1-5>,
        "revenueTrajectory": "<one of: accelerating, steady, decelerating, declining>",
        "marginTrajectory": "<one of: expanding, stable, compressing>",
        "reinvestmentRunway": "<one of: long, moderate, limited>",
        "summary": "<2-3 sentences on growth sustainability and drivers>"
    }},
    "riskAssessment": {{
        "overallRisk": "<one of: low, moderate, elevated, high>",
        "keyRisks": [
            "<risk 1: specific, concrete risk - not generic>",
            "<risk 2>",
            "<risk 3>"
        ],
        "industryDisruptionRisk": "<one of: low, moderate, high>",
        "cyclicality": "<one of: non_cyclical, mildly_cyclical, cyclical, highly_cyclical>",
        "summary": "<2-3 sentences on the most material risks>"
    }},
    "overallAssessment": {{
        "qualityScore": <1-5, overall business quality>,
        "confidenceLevel": "<one of: high, moderate, low>",
        "oneLineSummary": "<single sentence capturing the investment thesis or concern>",
        "strengthsTopThree": ["<strength 1>", "<strength 2>", "<strength 3>"],
        "weaknessesTopThree": ["<weakness 1>", "<weakness 2>", "<weakness 3>"]
    }}
}}"""
    return prompt
