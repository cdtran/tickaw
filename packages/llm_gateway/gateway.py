"""Application-facing LLM gateway boundary.

The eventual gateway resolves a stable model ID through the registry, delegates
to an adapter, normalizes the result, and emits observability/audit data.
"""
