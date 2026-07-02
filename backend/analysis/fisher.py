"""
Fisher Checklist Engine

Scores stocks against Philip Fisher's 15-point checklist from
Common Stocks and Uncommon Profits. 12 points are automated,
3 require manual review and are flagged.
"""

import statistics


def safe_div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def score_fisher(profile, income, balance, cashflow):
    """
    Run Fisher 15-point checklist analysis.

    Args:
        profile: list with one profile dict
        income: list of annual income statements (most recent first)
        balance: list of annual balance sheets (most recent first)
        cashflow: list of annual cash flow statements (most recent first)

    Returns:
        dict with scores, details, totalScore, maxScore, pctScore, grade, manualReviewCount
    """
    scores = {}
    details = {}

    n_income = len(income)
    n_balance = len(balance)
    n_cashflow = len(cashflow)

    # 1. Sales Growth Potential - Revenue CAGR over available years
    if n_income >= 2:
        recent_rev = income[0].get("revenue")
        oldest_rev = income[-1].get("revenue")
        years = n_income - 1
        if recent_rev and oldest_rev and oldest_rev > 0 and years > 0:
            cagr = (recent_rev / oldest_rev) ** (1 / years) - 1
        else:
            cagr = None

        if cagr is not None:
            if cagr > 0.10:
                scores["salesGrowth"] = 1.0
            elif cagr > 0.05:
                scores["salesGrowth"] = 0.5
            else:
                scores["salesGrowth"] = 0
        else:
            scores["salesGrowth"] = 0
        details["salesGrowth"] = {
            "label": "Sales Growth Potential",
            "value": f"{cagr * 100:.1f}% CAGR" if cagr is not None else "N/A",
            "threshold": "> 10% (full), > 5% (half)",
            "point": 1,
        }
    else:
        scores["salesGrowth"] = 0
        details["salesGrowth"] = {
            "label": "Sales Growth Potential",
            "value": "Insufficient data",
            "threshold": "> 10% (full), > 5% (half)",
            "point": 1,
        }

    # 2. R&D Commitment - R&D / Revenue
    latest = income[0] if income else {}
    rd = latest.get("researchAndDevelopmentExpenses")
    rev = latest.get("revenue")
    rd_ratio = safe_div(rd, rev)

    if rd is not None and rd > 0 and rd_ratio is not None:
        if rd_ratio > 0.05:
            scores["rdCommitment"] = 1.0
        elif rd_ratio > 0.02:
            scores["rdCommitment"] = 0.5
        else:
            scores["rdCommitment"] = 0
        details["rdCommitment"] = {
            "label": "R&D Commitment",
            "value": f"{rd_ratio * 100:.1f}% of revenue",
            "threshold": "> 5% (full), > 2% (half)",
            "point": 2,
        }
    else:
        scores["rdCommitment"] = None  # Flag for manual check
        details["rdCommitment"] = {
            "label": "R&D Commitment",
            "value": "No R&D reported - check manually",
            "threshold": "> 5% (full), > 2% (half)",
            "point": 2,
            "manualCheck": True,
        }

    # 3. R&D Effectiveness - Gross margin trend over 3 years
    if n_income >= 3:
        margins = []
        for stmt in income[:3]:
            gp = stmt.get("grossProfit")
            r = stmt.get("revenue")
            m = safe_div(gp, r)
            if m is not None:
                margins.append(m)

        if len(margins) >= 2:
            # margins[0] is most recent, margins[-1] is oldest
            change_pp = (margins[0] - margins[-1]) * 100
            if change_pp > 2:
                scores["rdEffectiveness"] = 1.0
            elif abs(change_pp) <= 1:
                scores["rdEffectiveness"] = 0.5
            else:
                scores["rdEffectiveness"] = 0
            details["rdEffectiveness"] = {
                "label": "R&D Effectiveness (Gross Margin Trend)",
                "value": f"{change_pp:+.1f}pp over {len(margins)} years",
                "threshold": "Improving > 2pp (full), stable (half)",
                "point": 3,
            }
        else:
            scores["rdEffectiveness"] = 0
            details["rdEffectiveness"] = {
                "label": "R&D Effectiveness (Gross Margin Trend)",
                "value": "Insufficient data",
                "threshold": "Improving > 2pp (full), stable (half)",
                "point": 3,
            }
    else:
        scores["rdEffectiveness"] = 0
        details["rdEffectiveness"] = {
            "label": "R&D Effectiveness (Gross Margin Trend)",
            "value": "Insufficient data",
            "threshold": "Improving > 2pp (full), stable (half)",
            "point": 3,
        }

    # 4. Sales Organization Efficiency - SGA / Revenue
    sga = latest.get("sellingGeneralAndAdministrativeExpenses")
    sga_ratio = safe_div(sga, rev)
    if sga_ratio is not None:
        if sga_ratio < 0.25:
            scores["salesEfficiency"] = 1.0
        elif sga_ratio < 0.35:
            scores["salesEfficiency"] = 0.5
        else:
            scores["salesEfficiency"] = 0
    else:
        scores["salesEfficiency"] = 0
    details["salesEfficiency"] = {
        "label": "Sales Organization Efficiency (SGA/Rev)",
        "value": f"{sga_ratio * 100:.1f}%" if sga_ratio is not None else "N/A",
        "threshold": "< 25% (full), < 35% (half)",
        "point": 4,
    }

    # 5. Worthwhile Profit Margin - Operating Income / Revenue
    op_income = latest.get("operatingIncome")
    op_margin = safe_div(op_income, rev)
    if op_margin is not None:
        if op_margin > 0.15:
            scores["profitMargin"] = 1.0
        elif op_margin > 0.08:
            scores["profitMargin"] = 0.5
        else:
            scores["profitMargin"] = 0
    else:
        scores["profitMargin"] = 0
    details["profitMargin"] = {
        "label": "Worthwhile Profit Margin",
        "value": f"{op_margin * 100:.1f}%" if op_margin is not None else "N/A",
        "threshold": "> 15% (full), > 8% (half)",
        "point": 5,
    }

    # 6. Margin Improvement - Operating margin change over 3 years
    if n_income >= 3:
        op_margins = []
        for stmt in income[:3]:
            oi = stmt.get("operatingIncome")
            r = stmt.get("revenue")
            m = safe_div(oi, r)
            if m is not None:
                op_margins.append(m)

        if len(op_margins) >= 2:
            change_pp = (op_margins[0] - op_margins[-1]) * 100
            if change_pp > 1:
                scores["marginImprovement"] = 1.0
            elif abs(change_pp) <= 1:
                scores["marginImprovement"] = 0.5
            else:
                scores["marginImprovement"] = 0
            details["marginImprovement"] = {
                "label": "Margin Improvement",
                "value": f"{change_pp:+.1f}pp",
                "threshold": "Improving > 1pp (full), stable (half)",
                "point": 6,
            }
        else:
            scores["marginImprovement"] = 0
            details["marginImprovement"] = {
                "label": "Margin Improvement",
                "value": "Insufficient data",
                "threshold": "Improving > 1pp (full), stable (half)",
                "point": 6,
            }
    else:
        scores["marginImprovement"] = 0
        details["marginImprovement"] = {
            "label": "Margin Improvement",
            "value": "Insufficient data",
            "threshold": "Improving > 1pp (full), stable (half)",
            "point": 6,
        }

    # 7. Labor Relations - SGA ratio std dev over 3 years (stability proxy)
    if n_income >= 3:
        sga_ratios = []
        for stmt in income[:3]:
            s = stmt.get("sellingGeneralAndAdministrativeExpenses")
            r = stmt.get("revenue")
            ratio = safe_div(s, r)
            if ratio is not None:
                sga_ratios.append(ratio * 100)

        if len(sga_ratios) >= 2:
            std = statistics.stdev(sga_ratios)
            if std < 2:
                scores["laborRelations"] = 1.0
            elif std < 5:
                scores["laborRelations"] = 0.5
            else:
                scores["laborRelations"] = 0
            details["laborRelations"] = {
                "label": "Labor Relations (SGA Stability)",
                "value": f"σ = {std:.1f}%",
                "threshold": "σ < 2% (full), < 5% (half)",
                "point": 7,
            }
        else:
            scores["laborRelations"] = 0
            details["laborRelations"] = {
                "label": "Labor Relations (SGA Stability)",
                "value": "Insufficient data",
                "threshold": "σ < 2% (full), < 5% (half)",
                "point": 7,
            }
    else:
        scores["laborRelations"] = 0
        details["laborRelations"] = {
            "label": "Labor Relations (SGA Stability)",
            "value": "Insufficient data",
            "threshold": "σ < 2% (full), < 5% (half)",
            "point": 7,
        }

    # 8. Executive Relations - Average ROE over 3 years
    if n_income >= 3 and n_balance >= 3:
        roes = []
        for i in range(min(3, n_income, n_balance)):
            ni = income[i].get("netIncome")
            eq = balance[i].get("totalStockholdersEquity")
            roe = safe_div(ni, eq)
            if roe is not None:
                roes.append(roe)

        if roes:
            avg_roe = sum(roes) / len(roes)
            if avg_roe > 0.15:
                scores["executiveRelations"] = 1.0
            elif avg_roe > 0.10:
                scores["executiveRelations"] = 0.5
            else:
                scores["executiveRelations"] = 0
            details["executiveRelations"] = {
                "label": "Executive Relations (Avg ROE)",
                "value": f"{avg_roe * 100:.1f}%",
                "threshold": "> 15% (full), > 10% (half)",
                "point": 8,
            }
        else:
            scores["executiveRelations"] = 0
            details["executiveRelations"] = {
                "label": "Executive Relations (Avg ROE)",
                "value": "N/A",
                "threshold": "> 15% (full), > 10% (half)",
                "point": 8,
            }
    else:
        scores["executiveRelations"] = 0
        details["executiveRelations"] = {
            "label": "Executive Relations (Avg ROE)",
            "value": "Insufficient data",
            "threshold": "> 15% (full), > 10% (half)",
            "point": 8,
        }

    # 9. Management Depth (MANUAL)
    scores["managementDepth"] = None
    details["managementDepth"] = {
        "label": "Management Depth",
        "value": None,
        "threshold": "Manual review required",
        "point": 9,
        "manual": True,
        "question": "Does the company have depth to its management?",
    }

    # 10. Accounting Quality - Accruals ratio
    latest_cf = cashflow[0] if cashflow else {}
    latest_bs = balance[0] if balance else {}
    ni = latest.get("netIncome")
    ocf = latest_cf.get("operatingCashFlow")
    total_assets = latest_bs.get("totalAssets")

    if ni is not None and ocf is not None and total_assets and total_assets > 0:
        accruals = (ni - ocf) / total_assets
        if accruals < 0:
            scores["accountingQuality"] = 1.0
        elif accruals < 0.05:
            scores["accountingQuality"] = 0.5
        else:
            scores["accountingQuality"] = 0
        details["accountingQuality"] = {
            "label": "Accounting Quality (Accruals Ratio)",
            "value": f"{accruals * 100:.1f}%",
            "threshold": "< 0% (full), < 5% (half)",
            "point": 10,
        }
    else:
        scores["accountingQuality"] = 0
        details["accountingQuality"] = {
            "label": "Accounting Quality (Accruals Ratio)",
            "value": "N/A",
            "threshold": "< 0% (full), < 5% (half)",
            "point": 10,
        }

    # 11. Industry-Specific Advantages (MANUAL)
    scores["industryAdvantages"] = None
    details["industryAdvantages"] = {
        "label": "Industry-Specific Advantages",
        "value": None,
        "threshold": "Manual review required",
        "point": 11,
        "manual": True,
        "question": "Are there industry-specific aspects that give clues about competitive advantages?",
    }

    # 12. Long-Range Profit Outlook - Avg FCF margin over available years
    if n_cashflow >= 2:
        fcf_margins = []
        for i in range(min(5, n_cashflow, n_income)):
            fcf = cashflow[i].get("freeCashFlow")
            r = income[i].get("revenue") if i < n_income else None
            m = safe_div(fcf, r)
            if m is not None:
                fcf_margins.append(m)

        if fcf_margins:
            avg_fcf_margin = sum(fcf_margins) / len(fcf_margins)
            if avg_fcf_margin > 0.10:
                scores["longRangeOutlook"] = 1.0
            elif avg_fcf_margin > 0.05:
                scores["longRangeOutlook"] = 0.5
            else:
                scores["longRangeOutlook"] = 0
            details["longRangeOutlook"] = {
                "label": "Long-Range Profit Outlook (FCF Margin)",
                "value": f"{avg_fcf_margin * 100:.1f}%",
                "threshold": "> 10% (full), > 5% (half)",
                "point": 12,
            }
        else:
            scores["longRangeOutlook"] = 0
            details["longRangeOutlook"] = {
                "label": "Long-Range Profit Outlook (FCF Margin)",
                "value": "N/A",
                "threshold": "> 10% (full), > 5% (half)",
                "point": 12,
            }
    else:
        scores["longRangeOutlook"] = 0
        details["longRangeOutlook"] = {
            "label": "Long-Range Profit Outlook (FCF Margin)",
            "value": "Insufficient data",
            "threshold": "> 10% (full), > 5% (half)",
            "point": 12,
        }

    # 13. Share Dilution - Change in shares outstanding over 3 years
    if n_income >= 3:
        recent_shares = income[0].get("weightedAverageShsOut")
        old_shares = income[min(2, n_income - 1)].get("weightedAverageShsOut")

        if recent_shares and old_shares and old_shares > 0:
            dilution = (recent_shares - old_shares) / old_shares
            if dilution < 0:
                scores["shareDilution"] = 1.0  # Buyback
            elif dilution < 0.03:
                scores["shareDilution"] = 0.5
            else:
                scores["shareDilution"] = 0
            details["shareDilution"] = {
                "label": "Share Dilution",
                "value": f"{dilution * 100:+.1f}%",
                "threshold": "Buyback (full), < 3% dilution (half)",
                "point": 13,
            }
        else:
            scores["shareDilution"] = 0
            details["shareDilution"] = {
                "label": "Share Dilution",
                "value": "N/A",
                "threshold": "Buyback (full), < 3% dilution (half)",
                "point": 13,
            }
    else:
        scores["shareDilution"] = 0
        details["shareDilution"] = {
            "label": "Share Dilution",
            "value": "Insufficient data",
            "threshold": "Buyback (full), < 3% dilution (half)",
            "point": 13,
        }

    # 14. Management Communication (MANUAL)
    scores["managementComm"] = None
    details["managementComm"] = {
        "label": "Management Communication",
        "value": None,
        "threshold": "Manual review required",
        "point": 14,
        "manual": True,
        "question": "Does management talk freely when things go well but clam up during troubles?",
    }

    # 15. Management Integrity (MANUAL)
    scores["managementIntegrity"] = None
    details["managementIntegrity"] = {
        "label": "Management Integrity",
        "value": None,
        "threshold": "Manual review required",
        "point": 15,
        "manual": True,
        "question": "Does management have unquestionable integrity?",
    }

    # ---- Data completeness (additive metadata; does not affect scoring) ----
    # Was the required input data present for each *automated* criterion?
    # Manual (judgment) items get None — they aren't data-dependent.
    def _has(*vals):
        return all(v is not None for v in vals)

    def _all_present(stmts, field, need):
        """True if at least `need` of the first `need` statements have `field`
        non-None."""
        if len(stmts) < need:
            return False
        return all(s.get(field) is not None for s in stmts[:need])

    # R&D special case: 0 is legitimately "reported zero R&D" (banks, staples),
    # so data IS available. Only None (field absent) means unavailable.
    rd_present = latest.get("researchAndDevelopmentExpenses") is not None and rev is not None

    data_available = {
        "salesGrowth": _all_present(income, "revenue", 2),
        "rdCommitment": rd_present,
        "rdEffectiveness": (
            _all_present(income, "grossProfit", 3) and _all_present(income, "revenue", 3)
        ),
        "salesEfficiency": _has(sga, rev),
        "profitMargin": _has(op_income, rev),
        "marginImprovement": (
            _all_present(income, "operatingIncome", 3) and _all_present(income, "revenue", 3)
        ),
        "laborRelations": (
            _all_present(income, "sellingGeneralAndAdministrativeExpenses", 3)
            and _all_present(income, "revenue", 3)
        ),
        "executiveRelations": (
            _all_present(income, "netIncome", 3)
            and _all_present(balance, "totalStockholdersEquity", 3)
        ),
        "accountingQuality": _has(ni, ocf, total_assets),
        "longRangeOutlook": (
            _all_present(cashflow, "freeCashFlow", 3) and _all_present(income, "revenue", 3)
        ),
        "shareDilution": _all_present(income, "weightedAverageShsOut", 3),
        # Manual / judgment items — not data-dependent.
        "managementDepth": None,
        "industryAdvantages": None,
        "managementComm": None,
        "managementIntegrity": None,
    }

    # Completeness measured only over the automated (data-dependent) criteria.
    auto_avail = {k: v for k, v in data_available.items() if v is not None}
    available_count = sum(1 for ok in auto_avail.values() if ok)
    criteria_count = len(auto_avail)
    data_completeness = (
        round(available_count / criteria_count, 3) if criteria_count else 0
    )
    missing_count = criteria_count - available_count
    completeness_note = (
        f"{missing_count} of {criteria_count} automated criteria could not be evaluated due to missing data"
        if missing_count else "All automated criteria had data available"
    )

    # Compute totals - only over auto-scored items (non-None)
    auto_scores = {k: v for k, v in scores.items() if v is not None}
    manual_items = {k: v for k, v in scores.items() if v is None}
    total_score = sum(auto_scores.values())
    max_score = len(auto_scores)
    pct_score = safe_div(total_score, max_score) if max_score > 0 else 0

    # adjustedPctScore counts only automated criteria that had data.
    adjusted_pct_score = (
        round(total_score / available_count, 3) if available_count > 0 else None
    )

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
        "dataAvailable": data_available,
        "dataCompleteness": data_completeness,
        "completenessNote": completeness_note,
        "totalScore": total_score,
        "maxScore": max_score,
        "pctScore": round(pct_score, 3) if pct_score else 0,
        "adjustedPctScore": adjusted_pct_score,
        "grade": grade,
        "manualReviewCount": len(manual_items),
    }
