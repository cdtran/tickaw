# LLM middleware design

## Goal

Make model selection a product-level concern rather than a provider SDK concern. The application uses a stable ID (for example, `analysis-default`); the middleware maps it to a configured provider and provider model.

## Core contracts to implement

`ModelDescriptor` should contain the stable ID, display name, provider, capabilities, enabled status, cost/tier metadata, and a provider model identifier kept server-side.

`AnalysisRequest` should contain the dataset profile reference, user question, selected stable model ID, prompt version, allowed operations, and a strict structured-output schema.

`AnalysisResult` should contain a validated plan/code payload, narrative, provider/model resolution, request ID, token usage, finish reason, latency, and prompt version.

`ProviderAdapter` should have one operation, conceptually `generate_analysis(request) -> result`. Implementations translate only at the adapter edge.

`LLMGateway` should resolve the stable ID, select the adapter, apply retries/timeouts/rate limits, normalize errors, capture audit metadata, and return `AnalysisResult`.

## Recommended configuration pattern

Store stable-model mappings in configuration at first, then migrate them to an administrator-managed database table if you need runtime changes. Example conceptual mapping:

| Stable ID | Provider | Provider model | Intended use |
| --- | --- | --- | --- |
| `analysis-default` | provider configured server-side | configured server-side | General analysis |
| `analysis-fast` | provider configured server-side | configured server-side | Lower-latency requests |
| `analysis-premium` | provider configured server-side | configured server-side | Complex analysis |

Do not expose provider API keys or unrestricted raw provider model names to the browser. The model-list endpoint should return enabled `ModelDescriptor` values only.

## Swapping a model

1. Add or update an adapter only if the provider is new.
2. Update the registry mapping for the stable ID.
3. Leave notebook-cell requests and UI selection unchanged.
4. Record both stable ID and resolved provider/model with each completed analysis so prior results remain attributable.

## Safety and reliability

- Send only a bounded, sanitized dataset profile to the LLM—not the entire uploaded file by default.
- Require schema-constrained output, then validate it before execution.
- Apply per-provider timeouts, retries, circuit breaking, and rate limits in the gateway.
- Keep logs redacted; never log API credentials or raw sensitive cells.
- Treat generated code as untrusted and execute it only through the sandbox in `packages/data_engine`.
