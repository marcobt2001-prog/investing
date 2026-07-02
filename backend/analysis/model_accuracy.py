"""Per-industry valuation-model accuracy (Phase 3, Part 3).

Not a regression — a simple accuracy ranking. For each company with enough
history we ask: how close was each model's intrinsic-value estimate N years
ago to the stock's actual average price N years later? Aggregate those
prediction errors by industry; the model with the lowest average error is the
most predictive for that industry, and we turn errors into recommended
blending weights (inverse-error, normalized).

Depends on the `historical_valuations` rows written in Step 3 and the
`daily_prices` table for realized prices.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

from analysis.iv_trends import MODELS, _avg_price_for_year

log = logging.getLogger(__name__)

HORIZONS = (1, 3, 5)
MIN_POINTS_PER_MODEL = 3   # need >= 3 (prediction, actual) pairs to trust an error
MIN_COMPANIES_FOR_INDUSTRY = 1  # aggregate even a single company; caller can gate higher


# ----------------------------- per-company -----------------------------

def compute_model_accuracy(symbol: str,
                           historical_valuations: Optional[list[dict]] = None,
                           daily_prices: Optional[list[dict]] = None) -> dict:
    """Prediction error per model at 1/3/5-year horizons for one company.

    For a prediction made in year Y at value P, the actual is the average
    price in year Y+h. Error = |P - actual| / actual. We average that error
    over all years where both the prediction and the future price exist.

    Args:
        symbol: ticker.
        historical_valuations: rows from get_historical_valuations(symbol).
            Loaded from the DB if omitted.
        daily_prices: rows from get_daily_prices(symbol). Loaded if omitted.

    Returns {model: {"error_1yr", "error_3yr", "error_5yr"}} with None where
    there are fewer than MIN_POINTS_PER_MODEL usable pairs.
    """
    from database import models as _m

    if historical_valuations is None:
        historical_valuations = _m.get_historical_valuations(symbol)
    if daily_prices is None:
        daily_prices = _m.get_daily_prices(symbol)

    # Index predicted IV: {model: {year: intrinsic_value}}
    predicted: dict[str, dict[int, float]] = {mdl: {} for mdl in MODELS}
    for row in historical_valuations:
        mdl = row.get("model")
        iv = row.get("intrinsic_value")
        yr = row.get("fiscal_year")
        if mdl in predicted and iv is not None and yr is not None:
            predicted[mdl][yr] = iv

    # Cache realized average prices per year on demand.
    price_cache: dict[int, Optional[float]] = {}

    def _actual(year: int) -> Optional[float]:
        if year not in price_cache:
            price_cache[year] = _avg_price_for_year(daily_prices, year)
        return price_cache[year]

    out: dict[str, dict] = {}
    for mdl in MODELS:
        model_errors: dict[int, list[float]] = {h: [] for h in HORIZONS}
        for year, iv in predicted[mdl].items():
            # NCAV and others can be negative — a negative "intrinsic value"
            # isn't a meaningful price prediction, so skip it.
            if iv is None or iv <= 0:
                continue
            for h in HORIZONS:
                actual = _actual(year + h)
                if actual is None or actual <= 0:
                    continue
                model_errors[h].append(abs(iv - actual) / actual)

        entry = {}
        for h in HORIZONS:
            errs = model_errors[h]
            key = f"error_{h}yr"
            if len(errs) >= MIN_POINTS_PER_MODEL:
                entry[key] = round(sum(errs) / len(errs), 4)
            else:
                entry[key] = None
        out[mdl] = entry

    return out


# ----------------------------- per-industry -----------------------------

def _weights_from_errors(errors_by_model: dict[str, Optional[float]]) -> dict[str, float]:
    """Inverse-error weights normalized to sum to 1.

    Models with None error get weight 0. If every model is None, returns an
    empty dict.
    """
    inv: dict[str, float] = {}
    for mdl, err in errors_by_model.items():
        if err is None or err <= 0:
            continue
        inv[mdl] = 1.0 / err
    total = sum(inv.values())
    if total <= 0:
        return {}
    return {mdl: v / total for mdl, v in inv.items()}


def compute_industry_model_accuracy(industry: str) -> dict:
    """Aggregate per-model 3-year prediction error across an industry.

    Averages each model's per-company 3yr error (and 1yr/5yr for reference)
    across all companies in the industry that have enough history, then ranks
    models and derives recommended blending weights.

    Returns a dict with model_rankings, best_model_3yr, and recommended_weights.
    """
    from database import models as _m

    companies = _m.get_companies_by_industry(industry)
    # Accumulate errors across companies: {model: {horizon: [errors]}}
    agg: dict[str, dict[int, list[float]]] = {
        mdl: {h: [] for h in HORIZONS} for mdl in MODELS
    }
    contributing = 0

    for comp in companies:
        sym = comp["symbol"]
        acc = compute_model_accuracy(sym)
        used = False
        for mdl in MODELS:
            for h in HORIZONS:
                err = acc.get(mdl, {}).get(f"error_{h}yr")
                if err is not None:
                    agg[mdl][h].append(err)
                    used = True
        if used:
            contributing += 1

    # Average per model/horizon and sample sizes (3yr is the primary).
    model_avgs: dict[str, dict] = {}
    for mdl in MODELS:
        entry = {"sample_size": len(agg[mdl][3])}
        for h in HORIZONS:
            errs = agg[mdl][h]
            entry[f"avg_error_{h}yr"] = round(sum(errs) / len(errs), 4) if errs else None
        model_avgs[mdl] = entry

    # Weights from the 3yr errors.
    errs_3yr = {mdl: model_avgs[mdl]["avg_error_3yr"] for mdl in MODELS}
    weights = _weights_from_errors(errs_3yr)

    # Rank by 3yr error (lower = better). Models with no error rank last.
    ranked = sorted(
        MODELS,
        key=lambda m: (model_avgs[m]["avg_error_3yr"] is None,
                       model_avgs[m]["avg_error_3yr"] if model_avgs[m]["avg_error_3yr"] is not None else float("inf")),
    )
    rankings: dict[str, dict] = {}
    for rank, mdl in enumerate(ranked, 1):
        rankings[mdl] = {
            "avg_error_1yr": model_avgs[mdl]["avg_error_1yr"],
            "avg_error_3yr": model_avgs[mdl]["avg_error_3yr"],
            "avg_error_5yr": model_avgs[mdl]["avg_error_5yr"],
            "sample_size": model_avgs[mdl]["sample_size"],
            "rank": rank,
            "weight": round(weights.get(mdl, 0.0), 4),
        }

    # Best model = rank 1 that actually has an error.
    best = None
    for mdl in ranked:
        if model_avgs[mdl]["avg_error_3yr"] is not None:
            best = mdl
            break

    return {
        "industry": industry,
        "company_count": len(companies),
        "contributing_companies": contributing,
        "best_model_3yr": best,
        "model_rankings": rankings,
        "recommended_weights": {mdl: round(weights.get(mdl, 0.0), 4) for mdl in MODELS},
    }


def store_industry_model_accuracy(industry: str) -> dict:
    """Compute and persist model accuracy for an industry into the
    `model_accuracy` table. Returns the computed dict."""
    from database import models as _m

    result = compute_industry_model_accuracy(industry)
    for mdl, r in result["model_rankings"].items():
        _m.upsert_model_accuracy(
            industry, mdl,
            avg_error_1yr=r["avg_error_1yr"],
            avg_error_3yr=r["avg_error_3yr"],
            avg_error_5yr=r["avg_error_5yr"],
            sample_size=r["sample_size"],
            rank_3yr=r["rank"],
            recommended_weight=r["weight"],
        )
    return result


# ----------------------------- weighted IV -----------------------------

# Map between the valuation engine's model keys and our accuracy model keys.
_ENGINE_TO_ACC = {
    "graham": "graham",
    "dcf": "dcf",
    "bookValue": "book_value",
    "epv": "epv",
    "ncav": "ncav",
}


def compute_weighted_intrinsic_value(symbol: str, valuations: dict,
                                     industry_weights: dict) -> Optional[float]:
    """Blend per-model intrinsic values using industry-specific weights.

    Args:
        symbol: ticker (for logging).
        valuations: output of valuation.compute_valuations() — has
            ["models"][engine_key]["intrinsicValue"].
        industry_weights: recommended_weights keyed by accuracy model name
            (graham/dcf/book_value/epv/ncav).

    Returns the weighted per-share IV, renormalizing over whichever models
    actually produced a positive value. None if nothing usable.
    """
    engine_models = (valuations or {}).get("models", {}) or {}

    num = 0.0
    wsum = 0.0
    for engine_key, model in engine_models.items():
        acc_key = _ENGINE_TO_ACC.get(engine_key)
        if acc_key is None:
            continue
        iv = model.get("intrinsicValue")
        w = industry_weights.get(acc_key, 0.0)
        if iv is None or iv <= 0 or w <= 0:
            continue
        num += iv * w
        wsum += w

    if wsum <= 0:
        return None
    return round(num / wsum, 2)
