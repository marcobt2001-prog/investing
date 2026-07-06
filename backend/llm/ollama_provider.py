"""Ollama local model provider. Calls the Ollama REST API on localhost.

No new dependencies — Ollama exposes a simple REST API and `requests` is
already installed. When Ollama isn't running (or the model isn't downloaded),
is_available() returns False rather than raising, so the app degrades cleanly.
"""

import logging

import requests

from llm.provider import LLMProvider

log = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    def __init__(self, config: dict):
        self.base_url = (config.get("ollama_base_url") or "http://localhost:11434").rstrip("/")
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
        """True if Ollama is running AND the configured model is downloaded."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code == 200:
                models = [m.get("name", "") for m in resp.json().get("models", [])]
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
