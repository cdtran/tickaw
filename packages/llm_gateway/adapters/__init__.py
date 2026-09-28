"""Vendor-specific adapter implementations belong in this package."""
from packages.llm_gateway.adapters.openai_compatible import OpenAICompatibleAdapter

__all__ = ["OpenAICompatibleAdapter"]
