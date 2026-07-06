# LLM Qualitative Evaluation Module — Spec

## Overview

Add an AI-powered qualitative evaluation layer that analyzes a company's financial
statements and produces a structured risk/quality assessment. This complements the
quantitative Graham/Fisher scores with the kind of contextual analysis a human
analyst would do — identifying risks, moats, earnings quality issues, and capital
allocation patterns that numbers alone don't capture.

The module uses a pluggable LLM backend: Claude API (best quality, small cost per
call) or Ollama local models (free, slower, lower quality).

---

## Architecture

```
backend/
├── llm/
│   ├── __init__.py
│   ├── provider.py          # Abstract provider + factory
│   ├── claude_provider.py   # Claude API (Anthropic SDK)
│   ├── ollama_provider.py   # Ollama local models
│   ├── prompts.py           # All evaluation prompts
│   ├── evaluator.py         # Main evaluation orchestrator
│   └── config.py            # LLM configuration (provider, model, API key)
├── analysis/                # Existing — unchanged
├── app.py                   # Updated: new routes
frontend/
└── src/
    └── components/
        ├── Analysis.jsx     # Updated: LLM evaluation display
        └── LLMSettings.jsx  # NEW: provider/model configuration UI
```

---

## Part 1: Pluggable LLM Provider

### `llm/config.py`

```python
"""
LLM configuration. Reads from environment variables or a local config file.
Supports runtime switching between providers.
"""

import os
import json

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "llm_config.json")

DEFAULTS = {
    "provider": "claude",          # "claude" or "ollama"
    "claude_api_key": None,        # Set via env ANTHROPIC_API_KEY or config
    "claude_model": "claude-sonnet-4-6",
    "ollama_base_url": "http://localhost:11434",
    "ollama_model": "llama3.1:8b", # Or "mistral", "phi3", etc.
    "max_tokens": 4096,
    "temperature": 0.3,            # Low temperature for analytical consistency
}

def load_config() -> dict:
    """Load config from file, overlaid with environment variables."""
    config = dict(DEFAULTS)

    # Load from file if exists
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            file_config = json.load(f)
            config.update(file_config)

    # Environment overrides
    if os.environ.get("ANTHROPIC_API_KEY"):
        config["claude_api_key"] = os.environ["ANTHROPIC_API_KEY"]
    if os.environ.get("LLM_PROVIDER"):
        config["provider"] = os.environ["LLM_PROVIDER"]
    if os.environ.get("OLLAMA_MODEL"):
        config["ollama_model"] = os.environ["OLLAMA_MODEL"]

    return config

def save_config(config: dict):
    """Save config to file (for UI-driven configuration)."""
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
```

### `llm/provider.py`

```python
"""Abstract LLM provider interface and factory."""

from abc import ABC, abstractmethod

class LLMProvider(ABC):
    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Send a prompt and return the text response."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider is configured and reachable."""
        pass

    @abstractmethod
    def get_info(self) -> dict:
        """Return provider name, model, and status."""
        pass

def get_provider(config: dict) -> LLMProvider:
    """Factory: return the configured provider."""
    if config["provider"] == "claude":
        from llm.claude_provider import ClaudeProvider
        return ClaudeProvider(config)
    elif config["provider"] == "ollama":
        from llm.ollama_provider import OllamaProvider
        return OllamaProvider(config)
    else:
        raise ValueError(f"Unknown LLM provider: {config['provider']}")
```

### `llm/claude_provider.py`

```python
"""Claude API provider using the Anthropic Python SDK."""

import anthropic
from llm.provider import LLMProvider

class ClaudeProvider(LLMProvider):
    def __init__(self, config: dict):
        self.api_key = config.get("claude_api_key")
        self.model = config.get("claude_model", "claude-sonnet-4-6")
        self.max_tokens = config.get("max_tokens", 4096)
        self.temperature = config.get("temperature", 0.3)
        self.client = None
        if self.api_key:
            self.client = anthropic.Anthropic(api_key=self.api_key)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        if not self.client:
            raise RuntimeError("Claude API key not configured")
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text

    def is_available(self) -> bool:
        return self.client is not None

    def get_info(self) -> dict:
        return {
            "provider": "claude",
            "model": self.model,
            "available": self.is_available(),
        }
```

Add `anthropic` to `requirements.txt`.

### `llm/ollama_provider.py`

```python
"""Ollama local model provider. Calls the Ollama REST API on localhost."""

import requests
from llm.provider import LLMProvider

class OllamaProvider(LLMProvider):
    def __init__(self, config: dict):
        self.base_url = config.get("ollama_base_url", "http://localhost:11434")
        self.model = config.get("ollama_model", "llama3.1:8b")
        self.max_tokens = config.get("max_tokens", 4096)
        self.temperature = config.get("temperature", 0.3)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Call Ollama's /api/chat endpoint."""
        resp = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
                "options": {
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens,
                },
            },
            timeout=300,  # Local models can be slow on CPU
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    def is_available(self) -> bool:
        """Check if Ollama is running and the model is downloaded."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                return any(self.model in m for m in models)
        except Exception:
            pass
        return False

    def get_info(self) -> dict:
        return {
            "provider": "ollama",
            "model": self.model,
            "baseUrl": self.base_url,
            "available": self.is_available(),
        }
```

No new dependencies — Ollama uses a simple REST API, and `requests` is already installed.

---

## Part 2: Evaluation Prompts

### `llm/prompts.py`

This file contains all the structured prompts. The system prompt establishes the
role and output format. The user prompt is dynamically built from the company's
financial data.

```python
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


def build_evaluation_prompt(company: dict, financials: list[dict],
                             graham_scores: dict, fisher_scores: dict,
                             valuation: dict) -> str:
    """
    Build the user prompt with all financial data and context.

    The prompt includes:
    1. Company profile (name, sector, industry, market cap)
    2. Last 5 years of key financial metrics (formatted as a readable table)
    3. Graham and Fisher scores (so the LLM knows what the quant screen found)
    4. Current valuation estimates
    5. The evaluation request with exact JSON schema

    IMPORTANT: Format numbers readably (e.g. "$2.3B" not "2300000000").
    The LLM works better with human-readable numbers.
    """

    # Build financial summary table
    fin_table = _build_financial_table(financials[:5])

    # Build the prompt
    prompt = f"""Evaluate the following company based on its financial data.

## Company Profile
- Name: {company.get('name', 'Unknown')}
- Ticker: {company.get('symbol', 'Unknown')}
- Sector: {company.get('sector', 'Unknown')}
- Industry: {company.get('industry', 'Unknown')}
- Market Cap: {_fmt_large(company.get('market_cap'))}
- Current Price: ${company.get('price', 0):.2f}

## Financial Data (Last 5 Years, Most Recent First)
{fin_table}

## Quantitative Scores (Already Computed)
- Graham Score: {graham_scores.get('grade', 'N/A')} ({graham_scores.get('pctScore', 0)*100:.0f}%)
- Fisher Score: {fisher_scores.get('grade', 'N/A')} ({fisher_scores.get('pctScore', 0)*100:.0f}%)
- Composite Intrinsic Value: ${valuation.get('compositeValue', 0):.2f}
- Current Signal: {valuation.get('signal', 'N/A')}
- Discount to Intrinsic Value: {(valuation.get('compositeDiscount', 0) or 0)*100:.1f}%

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
        "cashFlowAlignment": "<one of: strong, moderate, weak> — are earnings backed by real cash flow?",
        "revenueConcentration": "<one of: low, moderate, high> — dependence on few customers/products/regions",
        "redFlags": ["<list any accounting concerns, if none use empty list>"],
        "summary": "<2-3 sentences on earnings sustainability and quality>"
    }},
    "capitalAllocation": {{
        "score": <1-5>,
        "reinvestmentQuality": "<one of: excellent, good, fair, poor>",
        "acquisitionTrackRecord": "<one of: value_creating, neutral, value_destroying, not_applicable>",
        "shareholderReturns": "<one of: excellent, good, fair, poor> — dividends + buybacks at reasonable prices",
        "debtManagement": "<one of: conservative, moderate, aggressive, overleveraged>",
        "summary": "<2-3 sentences on how management deploys capital>"
    }},
    "growthOutlook": {{
        "score": <1-5>,
        "revenueTrajectory": "<one of: accelerating, steady, decelerating, declining>",
        "marginTrajectory": "<one of: expanding, stable, compressing>",
        "reinvestmentRunway": "<one of: long, moderate, limited> — room to grow by reinvesting profits",
        "summary": "<2-3 sentences on growth sustainability and drivers>"
    }},
    "riskAssessment": {{
        "overallRisk": "<one of: low, moderate, elevated, high>",
        "keyRisks": [
            "<risk 1: specific, concrete risk — not generic>",
            "<risk 2>",
            "<risk 3>"
        ],
        "industryDisruptionRisk": "<one of: low, moderate, high>",
        "cyclicality": "<one of: non_cyclical, mildly_cyclical, cyclical, highly_cyclical>",
        "summary": "<2-3 sentences on the most material risks>"
    }},
    "overallAssessment": {{
        "qualityScore": <1-5, overall business quality>,
        "confidenceLevel": "<one of: high, moderate, low> — how confident are you in this assessment given the available data",
        "oneLineSummary": "<single sentence capturing the investment thesis or concern>",
        "strengthsTopThree": ["<strength 1>", "<strength 2>", "<strength 3>"],
        "weaknessesTopThree": ["<weakness 1>", "<weakness 2>", "<weakness 3>"]
    }}
}}"""
    return prompt


def _build_financial_table(financials: list[dict]) -> str:
    """Format financials as a readable text table for the LLM."""
    if not financials:
        return "No financial data available."

    headers = ["Year", "Revenue", "Net Income", "Oper Income", "FCF",
               "Total Assets", "Total Debt", "Equity", "EPS",
               "Gross Margin", "Oper Margin", "ROE", "D/E"]

    rows = []
    for f in financials:
        year = f.get("fiscal_year", "?")
        rev = f.get("revenue")
        ni = f.get("net_income")
        oi = f.get("operating_income")
        fcf = f.get("free_cash_flow")
        ta = f.get("total_assets")
        td = f.get("total_debt")
        eq = f.get("total_stockholders_equity")
        eps = f.get("eps")
        gm = f.get("gross_margin")
        om = f.get("operating_margin")
        roe = f.get("roe")
        de = f.get("debt_to_equity")

        rows.append([
            str(year),
            _fmt_large(rev),
            _fmt_large(ni),
            _fmt_large(oi),
            _fmt_large(fcf),
            _fmt_large(ta),
            _fmt_large(td),
            _fmt_large(eq),
            f"${eps:.2f}" if eps else "N/A",
            f"{gm*100:.1f}%" if gm else "N/A",
            f"{om*100:.1f}%" if om else "N/A",
            f"{roe*100:.1f}%" if roe else "N/A",
            f"{de:.2f}" if de else "N/A",
        ])

    # Format as aligned text table
    col_widths = [max(len(headers[i]), max(len(r[i]) for r in rows)) for i in range(len(headers))]
    header_line = " | ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    separator = "-+-".join("-" * w for w in col_widths)
    data_lines = [" | ".join(c.ljust(w) for c, w in zip(row, col_widths)) for row in rows]

    return "\n".join([header_line, separator] + data_lines)


def _fmt_large(n) -> str:
    """Format large numbers readably."""
    if n is None:
        return "N/A"
    if abs(n) >= 1e9:
        return f"${n/1e9:.1f}B"
    if abs(n) >= 1e6:
        return f"${n/1e6:.1f}M"
    if abs(n) >= 1e3:
        return f"${n/1e3:.0f}K"
    return f"${n:.0f}"
```

---

## Part 3: Evaluation Orchestrator

### `llm/evaluator.py`

```python
"""Main evaluation orchestrator. Ties provider + prompts + data together."""

import json
import logging
from llm.config import load_config
from llm.provider import get_provider
from llm.prompts import SYSTEM_PROMPT, build_evaluation_prompt

log = logging.getLogger(__name__)

def evaluate_company(symbol: str) -> dict:
    """
    Run the full LLM qualitative evaluation for a company.

    1. Load company data from the database (profile, financials, scores)
    2. Build the evaluation prompt
    3. Send to the configured LLM provider
    4. Parse the JSON response
    5. Return the structured evaluation

    Returns the parsed evaluation dict, or an error dict if something fails.
    """
    from database import models
    from ingestion.db_adapter import to_analysis_inputs

    config = load_config()
    provider = get_provider(config)

    if not provider.is_available():
        return {"error": f"LLM provider '{config['provider']}' is not available. "
                         f"Check configuration."}

    # Load data from DB
    company = models.get_company(symbol)
    if not company:
        return {"error": f"Company {symbol} not found in database"}

    financials = models.get_financials(symbol, limit=10)
    if not financials:
        return {"error": f"No financial data for {symbol}"}

    scores = models.get_scores(symbol)
    if not scores:
        return {"error": f"No scores computed for {symbol}. Run analysis first."}

    # Parse stored score details
    graham_scores = {"grade": scores.get("graham_grade"),
                     "pctScore": scores.get("graham_pct", 0)}
    fisher_scores = {"grade": scores.get("fisher_grade"),
                     "pctScore": scores.get("fisher_pct", 0)}

    valuation = {
        "compositeValue": scores.get("intrinsic_value_composite"),
        "compositeDiscount": scores.get("discount_to_intrinsic"),
        "signal": scores.get("signal"),
    }

    # Build prompt
    user_prompt = build_evaluation_prompt(company, financials,
                                           graham_scores, fisher_scores, valuation)

    # Call LLM
    log.info("[%s] Sending evaluation request to %s (%s)",
             symbol, config["provider"], provider.get_info().get("model"))

    try:
        raw_response = provider.generate(SYSTEM_PROMPT, user_prompt)
    except Exception as e:
        log.exception("[%s] LLM call failed", symbol)
        return {"error": f"LLM call failed: {str(e)}"}

    # Parse JSON response
    try:
        # Strip markdown code fences if the LLM wrapped it
        cleaned = raw_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]  # Remove first line
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()

        evaluation = json.loads(cleaned)
    except json.JSONDecodeError as e:
        log.error("[%s] Failed to parse LLM response as JSON: %s", symbol, e)
        log.debug("Raw response: %s", raw_response[:500])
        return {"error": "LLM returned invalid JSON. Try again or switch providers.",
                "rawResponse": raw_response[:1000]}

    # Validate required fields exist
    required_sections = ["competitivePosition", "earningsQuality",
                         "capitalAllocation", "growthOutlook",
                         "riskAssessment", "overallAssessment"]
    missing = [s for s in required_sections if s not in evaluation]
    if missing:
        log.warning("[%s] LLM response missing sections: %s", symbol, missing)
        evaluation["_missingSections"] = missing

    # Add metadata
    evaluation["_meta"] = {
        "symbol": symbol,
        "provider": config["provider"],
        "model": provider.get_info().get("model"),
    }

    return evaluation


def get_llm_status() -> dict:
    """Return current LLM configuration and availability."""
    config = load_config()
    provider = get_provider(config)
    info = provider.get_info()
    info["configured"] = True
    return info
```

---

## Part 4: Database Storage for Evaluations

### New table: `llm_evaluations`

```sql
CREATE TABLE IF NOT EXISTS llm_evaluations (
    symbol TEXT PRIMARY KEY,
    evaluation TEXT NOT NULL,         -- Full JSON evaluation blob
    provider TEXT,                    -- "claude" or "ollama"
    model TEXT,                       -- "claude-sonnet-4-6", "llama3.1:8b", etc.
    quality_score INTEGER,           -- The 1-5 overallAssessment.qualityScore
    overall_risk TEXT,               -- riskAssessment.overallRisk
    moat_type TEXT,                  -- competitivePosition.moatType
    moat_durability TEXT,            -- competitivePosition.moatDurability
    confidence TEXT,                 -- overallAssessment.confidenceLevel
    created_at TEXT NOT NULL         -- ISO datetime
);
```

Store the full JSON blob but also extract key fields into columns so they can
be used in screener queries (e.g. "show me companies with moat_durability = strong
and overall_risk = low").

### New helpers in `models.py`

```python
def upsert_llm_evaluation(symbol: str, evaluation: dict, provider: str,
                           model: str):
    """Store an LLM evaluation. Extracts key fields for queryability."""

def get_llm_evaluation(symbol: str) -> dict:
    """Return the stored LLM evaluation for a symbol, or None."""
```

### Screener integration

Add optional filters to `screen_companies()`:
- `minQualityScore` — filter by LLM quality score (1-5)
- `moatDurability` — filter by moat durability (none, weak, moderate, strong)
- `overallRisk` — filter by risk level (low, moderate, elevated, high)

These only apply to companies that have been LLM-evaluated. Companies without
an evaluation are NOT excluded — they just can't be filtered on these fields.

---

## Part 5: Flask Routes

```
GET /api/llm/status
    Returns current LLM provider configuration and availability.
    {
        "provider": "claude",
        "model": "claude-sonnet-4-6",
        "available": true
    }

POST /api/llm/configure
    Body: {
        "provider": "claude",          // or "ollama"
        "claude_api_key": "sk-...",    // only needed for claude
        "claude_model": "claude-sonnet-4-6",
        "ollama_model": "llama3.1:8b"
    }
    Saves configuration. Returns updated status.

POST /api/llm/evaluate/<symbol>
    Runs the LLM evaluation for a company. Returns the structured evaluation.
    If a recent evaluation exists (< 30 days old), returns the cached version.
    Pass ?force=true to bypass cache.

    Returns the full evaluation JSON, same structure as the prompt schema.

GET /api/llm/evaluation/<symbol>
    Returns the stored evaluation for a company (no new LLM call).
    Returns 404 if no evaluation exists.
```

---

## Part 6: Frontend

### `LLMSettings.jsx` (new component)

A small settings panel accessible from the header or a settings icon.

- Provider toggle: Claude API / Ollama
- If Claude: API key input field (stored in backend config, not in browser)
- If Ollama: model name input, base URL input
- Status indicator: green dot if available, red if not
- "Test Connection" button

### Updated `Analysis.jsx`

After the existing Valuation Models section, add a new section:

**AI Qualitative Evaluation**

- "Run AI Evaluation" button (calls POST /api/llm/evaluate/<symbol>)
- Loading state while the LLM processes (can take 5-30 seconds)
- Once complete, display the evaluation in a structured layout:

**Score cards row (5 cards):**
1. Competitive Position — score (1-5), moat type badge, moat durability badge
2. Earnings Quality — score (1-5), cash flow alignment badge
3. Capital Allocation — score (1-5), debt management badge
4. Growth Outlook — score (1-5), trajectory badges
5. Risk Assessment — overall risk badge, cyclicality badge

**Each card expandable to show:**
- The summary text (2-3 sentences)
- The sub-fields (moat type, red flags list, etc.)

**Below the cards:**
- Overall Quality Score (large, prominent)
- One-line summary
- Top 3 Strengths (green bullets)
- Top 3 Weaknesses (red bullets)
- Key Risks (amber bullets)
- Confidence level indicator
- Meta info: which LLM provider/model generated this, when

**Visual style:**
- Same dark theme as the rest of the app
- Score badges: 5 = green, 4 = teal, 3 = amber, 2 = orange, 1 = red
- Risk badges: low = green, moderate = amber, elevated = orange, high = red
- Moat badges: strong = green, moderate = amber, weak = orange, none = red/gray

### Updated `Screener.jsx`

Add optional columns (visible when LLM evaluations exist):
- AI Quality (1-5 score)
- Moat
- Risk

These columns show "—" for companies without evaluations.
Do NOT add LLM-specific filters to the screener by default — only show
them as filter options if the user has evaluated at least 10 companies.

---

## Build Order

### Step 1: LLM provider infrastructure

1. Create `llm/` directory with `__init__.py`, `config.py`, `provider.py`.
2. Implement `claude_provider.py` — uses `anthropic` Python SDK.
3. Implement `ollama_provider.py` — uses Ollama REST API.
4. Add `anthropic>=0.39.0` to `requirements.txt`.
5. Test: instantiate both providers, check `is_available()` and `get_info()`.
   Claude should be available if an API key is set. Ollama should be available
   only if Ollama is actually running locally (it's fine if it's not — it should
   return `available: false` gracefully, not crash).

### Step 2: Evaluation prompts and orchestrator

1. Implement `prompts.py` with `SYSTEM_PROMPT` and `build_evaluation_prompt()`.
2. Implement `evaluator.py` with `evaluate_company()` and `get_llm_status()`.
3. Test: run `evaluate_company("AAPL")` with the Claude provider.
   Verify the response parses to valid JSON with all required sections.
   Print the evaluation to console and sanity-check it.

### Step 3: Database storage

1. Add `llm_evaluations` table to `db.py` schema.
2. Add helpers to `models.py`.
3. Update `evaluator.py` to store evaluations after computing them.
4. Update `evaluator.py` to check for cached evaluations before calling the LLM.
5. Test: evaluate a company, verify it's stored. Call again, verify cache is used.

### Step 4: Flask routes

1. Add `/api/llm/status`, `/api/llm/configure`, `/api/llm/evaluate/<symbol>`,
   `/api/llm/evaluation/<symbol>`.
2. Test all routes with curl.

### Step 5: Frontend — LLM settings

1. Create `LLMSettings.jsx` — provider selection, API key input, test button.
2. Add access point in the header (gear icon or "AI Settings" link).
3. Wire to `/api/llm/configure` and `/api/llm/status`.
4. Test: configure Claude API key through the UI, verify status shows available.

### Step 6: Frontend — evaluation display

1. Update `Analysis.jsx` with the AI evaluation section.
2. Add "Run AI Evaluation" button.
3. Display evaluation results in the structured card layout.
4. Handle loading, error, and cached states.
5. Add the optional AI columns to the screener table.

### Step 7: Test end-to-end

1. Configure Claude API key through the UI.
2. Analyze a company (e.g. KO) — verify quantitative scores display as before.
3. Click "Run AI Evaluation" — verify evaluation appears with all sections.
4. Evaluate 2-3 more companies.
5. Verify evaluations are cached (second click on same company returns instantly).
6. If you have Ollama installed, switch to Ollama provider and verify it works
   (slower but functional).
7. Verify screener shows AI Quality column for evaluated companies.

---

## Important Notes

- **The LLM evaluation is always on-demand, never automatic.** It should only
  run when the user clicks the button. Never during bulk ingestion or scoring.
  It's too slow and (for Claude API) costs money.

- **JSON parsing is the biggest failure mode.** LLMs sometimes return invalid
  JSON or wrap it in markdown fences. The evaluator must handle this gracefully:
  strip fences, attempt repair, and if parsing still fails, return a clear error
  with the raw response for debugging.

- **Temperature should be low (0.2-0.3).** We want consistent, analytical output,
  not creative variation. The same company should get roughly the same assessment
  across multiple runs.

- **The prompt is long (~2000 tokens with financial data) and the response is
  ~1000-1500 tokens.** At Claude Sonnet rates, that's roughly $0.02-0.04 per
  evaluation. Budget accordingly.

- **Ollama must be installed separately.** The app should handle Ollama not being
  installed gracefully — just show "not available" in the settings, don't crash.
  If the user wants to try local models later, they install Ollama and download
  a model, then switch the provider in the UI.

- **Don't modify existing analysis engines.** The LLM evaluation is a separate,
  additive layer. It reads from the same database but doesn't change how Graham,
  Fisher, or valuation scores work.
