# LLM gateway

This package is the application’s only boundary to language-model vendors. FastAPI services and worker tasks depend on `LLMGateway`, not on an SDK such as OpenAI or Anthropic.

## Boundary

```text
Analysis service / worker
          |
          v
      LLMGateway  -- stable model ID --> ModelRegistry
          |                                  |
          v                                  v
  normalized request/result            ProviderAdapter
                                             |
                        OpenAI / Anthropic / Bedrock / local runtime
```

The UI submits a stable, product-owned ID such as `analysis-default` or `analysis-fast`. `ModelRegistry` resolves that ID to a provider adapter and provider model name. This means a provider or model can be replaced in configuration without changing the API, UI, stored notebook cells, or analysis pipeline.

## Intended request flow

1. The API validates a requested stable model ID against the registry.
2. The analysis worker creates a provider-neutral request containing the user question, a safe dataset profile, permitted operations, and an expected response schema.
3. The gateway asks the selected adapter for a structured analysis plan.
4. The response is normalized, validated, recorded with the stable and resolved model identifiers, then passed to the execution boundary.

Provider SDK imports belong only inside `adapters/`. Do not leak provider messages, tool-call formats, exceptions, API keys, or raw model names through the rest of the application.

## Files

- `contracts.py` — provider-neutral request/result and model metadata contracts
- `gateway.py` — application-facing gateway boundary
- `registry.py` — stable-ID to provider-model routing policy
- `provider.py` — adapter protocol
- `adapters/` — one isolated adapter package per vendor
- `prompts.py` — versioned prompts shared across adapters
