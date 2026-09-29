"""Vendor-specific adapter implementations belong in this package."""
from packages.llm_gateway.adapters.ollama import OllamaAdapter
from packages.llm_gateway.adapters.openai_compatible import OpenAICompatibleAdapter

__all__ = ["OllamaAdapter", "OpenAICompatibleAdapter"]
