"""LLM configuration.

Reads from a local JSON file (llm_config.json next to backend/) overlaid with
environment variables. Supports runtime switching between providers via the UI.

Model note: the default Claude model is claude-sonnet-5 (current Sonnet tier —
near-Opus quality at Sonnet cost). The latest Claude models (Opus 4.8, Sonnet 5,
Opus 4.7) reject temperature/top_p/top_k with a 400, so the Claude provider does
NOT send temperature; low-variance analytical output comes from the prompt +
the model's default sampling. temperature is still honored by the Ollama path.
"""

import os
import json

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "llm_config.json")

DEFAULTS = {
    "provider": "claude",           # "claude" or "ollama"
    "claude_api_key": None,         # Set via env ANTHROPIC_API_KEY or config
    "claude_model": "claude-sonnet-5",
    "ollama_base_url": "http://localhost:11434",
    "ollama_model": "llama3.1:8b",  # Or "mistral", "phi3", etc.
    "max_tokens": 4096,
    "temperature": 0.3,             # Ollama only; ignored by the Claude provider
}


def load_config() -> dict:
    """Load config from file, overlaid with environment variables."""
    config = dict(DEFAULTS)

    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                file_config = json.load(f)
                if isinstance(file_config, dict):
                    config.update(file_config)
        except (ValueError, OSError):
            # Corrupt/unreadable config file: fall back to defaults + env.
            pass

    # Environment overrides
    if os.environ.get("ANTHROPIC_API_KEY"):
        config["claude_api_key"] = os.environ["ANTHROPIC_API_KEY"]
    if os.environ.get("LLM_PROVIDER"):
        config["provider"] = os.environ["LLM_PROVIDER"]
    if os.environ.get("OLLAMA_MODEL"):
        config["ollama_model"] = os.environ["OLLAMA_MODEL"]

    return config


def save_config(config: dict) -> None:
    """Persist config to file (for UI-driven configuration).

    Only whitelisted keys are written, so a stray field from the request body
    can't pollute the config file.
    """
    allowed = set(DEFAULTS.keys())
    to_save = {k: v for k, v in config.items() if k in allowed}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(to_save, f, indent=2)
