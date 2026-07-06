"""Evaluation orchestrator. Ties provider + prompts + DB data together.

evaluate_company() is always on-demand — never called during ingestion/scoring.
JSON parsing is the main failure mode for LLM output, so it strips markdown
fences and attempts a brace-slice repair before giving up with a clear error.
"""

import datetime as _dt
import json
import logging

from llm.config import load_config
from llm.provider import get_provider
from llm.prompts import SYSTEM_PROMPT, build_evaluation_prompt

log = logging.getLogger(__name__)

REQUIRED_SECTIONS = [
    "competitivePosition", "earningsQuality", "capitalAllocation",
    "growthOutlook", "riskAssessment", "overallAssessment",
]

# A cached evaluation is reused for this many days before a fresh LLM call is
# made (financial data changes slowly). `force=True` bypasses this entirely.
CACHE_MAX_AGE_DAYS = 30


def _cache_age_days(created_at: str):
    """Age in days of an ISO-timestamp cache entry, or None if unparseable."""
    if not created_at:
        return None
    try:
        ts = _dt.datetime.fromisoformat(created_at)
    except (ValueError, TypeError):
        return None
    return (_dt.datetime.utcnow() - ts).total_seconds() / 86400.0


def _scalar_fields(evaluation: dict) -> dict:
    """Pull the filterable scalar columns out of a parsed evaluation dict.

    Missing/malformed sections degrade to None rather than raising, so a
    partial LLM response is still cached and returnable.
    """
    comp = evaluation.get("competitivePosition") or {}
    risk = evaluation.get("riskAssessment") or {}
    overall = evaluation.get("overallAssessment") or {}
    q = overall.get("qualityScore")
    try:
        q = int(q) if q is not None else None
    except (ValueError, TypeError):
        q = None
    return {
        "quality_score": q,
        "overall_risk": risk.get("overallRisk"),
        "moat_type": comp.get("moatType"),
        "moat_durability": comp.get("moatDurability"),
        "confidence": overall.get("confidenceLevel"),
    }


def _extract_json(raw: str):
    """Best-effort parse of an LLM response into a dict.

    Handles: clean JSON, markdown-fenced JSON (```json ... ```), and leading/
    trailing prose around a JSON object (brace-slice fallback). Returns the
    parsed dict, or raises json.JSONDecodeError if nothing works.
    """
    cleaned = (raw or "").strip()

    # Strip a leading fence line (```json / ```) and a trailing fence.
    if cleaned.startswith("```"):
        # Drop the first line (the ``` or ```json marker).
        parts = cleaned.split("\n", 1)
        cleaned = parts[1] if len(parts) > 1 else ""
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Fallback: slice from the first { to the last } and retry.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(cleaned[start:end + 1])

    # Nothing worked — re-raise a decode error for the caller.
    return json.loads(cleaned)  # raises JSONDecodeError


def evaluate_company(symbol: str, force: bool = False) -> dict:
    """Run the full LLM qualitative evaluation for a company.

    Loads profile/financials/scores from the DB, builds the prompt, sends it to
    the configured provider, parses the JSON response, validates it, and returns
    the structured evaluation. Returns an {"error": ...} dict on any failure.

    Results are cached in the DB. A cached evaluation younger than
    CACHE_MAX_AGE_DAYS is returned without calling the LLM unless force=True.
    """
    from database import models

    symbol = symbol.upper()

    # Cache check first — a fresh cached result skips the (paid, slow) LLM call.
    if not force:
        cached = models.get_llm_evaluation(symbol)
        if cached and isinstance(cached.get("evaluation"), dict):
            age = _cache_age_days(cached.get("created_at"))
            if age is not None and age <= CACHE_MAX_AGE_DAYS:
                evaluation = cached["evaluation"]
                evaluation["_meta"] = {
                    "symbol": symbol,
                    "provider": cached.get("provider"),
                    "model": cached.get("model"),
                    "cached": True,
                    "createdAt": cached.get("created_at"),
                    "cacheAgeDays": round(age, 1),
                }
                return evaluation

    config = load_config()
    provider = get_provider(config)

    if not provider.is_available():
        return {"error": f"LLM provider '{config['provider']}' is not available. "
                         f"Check configuration."}

    company = models.get_company(symbol)
    if not company:
        return {"error": f"Company {symbol} not found in database"}

    financials = models.get_financials(symbol, limit=10)
    if not financials:
        return {"error": f"No financial data for {symbol}"}

    scores = models.get_scores(symbol)
    if not scores:
        return {"error": f"No scores computed for {symbol}. Run analysis first."}

    graham_scores = {"grade": scores.get("graham_grade"),
                     "pctScore": scores.get("graham_pct") or 0}
    fisher_scores = {"grade": scores.get("fisher_grade"),
                     "pctScore": scores.get("fisher_pct") or 0}
    valuation = {
        "compositeValue": scores.get("intrinsic_value_composite"),
        "compositeDiscount": scores.get("discount_to_intrinsic"),
        "signal": scores.get("signal"),
    }

    user_prompt = build_evaluation_prompt(company, financials,
                                          graham_scores, fisher_scores, valuation)

    log.info("[%s] Sending evaluation request to %s (%s)",
             symbol, config["provider"], provider.get_info().get("model"))

    try:
        raw_response = provider.generate(SYSTEM_PROMPT, user_prompt)
    except Exception as e:
        log.exception("[%s] LLM call failed", symbol)
        return {"error": f"LLM call failed: {str(e)}"}

    try:
        evaluation = _extract_json(raw_response)
        if not isinstance(evaluation, dict):
            raise ValueError("LLM returned JSON that is not an object")
    except (json.JSONDecodeError, ValueError) as e:
        log.error("[%s] Failed to parse LLM response as JSON: %s", symbol, e)
        log.debug("Raw response: %s", (raw_response or "")[:500])
        return {"error": "LLM returned invalid JSON. Try again or switch providers.",
                "rawResponse": (raw_response or "")[:1000]}

    missing = [s for s in REQUIRED_SECTIONS if s not in evaluation]
    if missing:
        log.warning("[%s] LLM response missing sections: %s", symbol, missing)
        evaluation["_missingSections"] = missing

    model_id = provider.get_info().get("model")

    # Cache the result (scalar columns pulled out for cheap screener filtering).
    try:
        scalars = _scalar_fields(evaluation)
        models.upsert_llm_evaluation(
            symbol, evaluation, config["provider"], model_id, **scalars
        )
    except Exception:
        # Caching is best-effort — a storage failure shouldn't lose the result.
        log.exception("[%s] Failed to cache LLM evaluation", symbol)

    evaluation["_meta"] = {
        "symbol": symbol,
        "provider": config["provider"],
        "model": model_id,
        "cached": False,
    }
    return evaluation


def get_llm_status() -> dict:
    """Return current LLM configuration and availability."""
    config = load_config()
    provider = get_provider(config)
    info = provider.get_info()
    info["configured"] = True
    return info
