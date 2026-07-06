"""Claude API provider using the Anthropic Python SDK.

Uses client.messages.create(...). Does NOT pass temperature: the current Claude
models (Sonnet 5, Opus 4.8/4.7) reject temperature/top_p/top_k with a 400.
Analytical consistency comes from the low-variance system prompt instead.
"""

import logging

from llm.provider import LLMProvider

log = logging.getLogger(__name__)


class ClaudeProvider(LLMProvider):
    def __init__(self, config: dict):
        self.api_key = config.get("claude_api_key")
        self.model = config.get("claude_model", "claude-sonnet-5")
        self.max_tokens = config.get("max_tokens", 4096)
        self.client = None
        if self.api_key:
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=self.api_key)
            except Exception:
                log.exception("Failed to construct Anthropic client")
                self.client = None

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        if not self.client:
            raise RuntimeError("Claude API key not configured")
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        # response.content is a list of content blocks; concatenate the text
        # blocks (a thinking block, if any, is skipped by the type guard).
        parts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
        return "".join(parts)

    def is_available(self) -> bool:
        return self.client is not None

    def get_info(self) -> dict:
        return {
            "provider": "claude",
            "model": self.model,
            "available": self.is_available(),
        }
