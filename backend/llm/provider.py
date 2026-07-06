"""Abstract LLM provider interface and factory."""

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Send a prompt and return the text response."""
        raise NotImplementedError

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider is configured and reachable."""
        raise NotImplementedError

    @abstractmethod
    def get_info(self) -> dict:
        """Return provider name, model, and status."""
        raise NotImplementedError


def get_provider(config: dict) -> LLMProvider:
    """Factory: return the configured provider."""
    provider = config.get("provider")
    if provider == "claude":
        from llm.claude_provider import ClaudeProvider
        return ClaudeProvider(config)
    elif provider == "ollama":
        from llm.ollama_provider import OllamaProvider
        return OllamaProvider(config)
    else:
        raise ValueError(f"Unknown LLM provider: {provider!r}")
