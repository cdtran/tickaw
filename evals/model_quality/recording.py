"""Evaluation-only response cache and metadata; never include prompts in reports."""

import hashlib
import json
from pathlib import Path
from time import perf_counter

from packages.llm_gateway.contracts import PlanResponse
from packages.llm_gateway.prompts import system_prompt


class RecordingGateway:
    def __init__(self, gateway, case, dataset, cache_dir: Path | None, refresh=False):
        self.gateway = gateway
        self.case = case
        self.dataset = dataset
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.attempts = 0
        self.cache_hits = 0
        self.input_tokens = []
        self.output_tokens = []
        self.duration_seconds = 0.0

    def generate_plan(self, model_id, request):
        route = self.gateway.registry.resolve(model_id)
        # Keep this aligned with provider adapter parameters. Include prompt text so
        # an accidentally unchanged prompt version cannot reuse stale responses.
        fingerprint = {
            "cache_version": 1,
            "case": self.case,
            "dataset": self.dataset,
            "request": request.model_dump(mode="json"),
            "system_prompt": system_prompt(),
            "model": model_id,
            "provider_model": route.provider_model,
            "provider": route.provider,
            "endpoint": route.base_url,
            "parameters": {
                "temperature": 0,
                "max_output_tokens": 1024,
                "think": False if route.provider == "ollama" else None,
            },
        }
        key = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
        path = self.cache_dir / f"{key}.json" if self.cache_dir else None
        self.attempts += 1
        start = perf_counter()
        try:
            response = None
            if path and path.exists() and not self.refresh:
                try:
                    response = PlanResponse.model_validate_json(path.read_text())
                    self.cache_hits += 1
                except (ValueError, OSError):
                    pass  # Corrupt entries are replaced by a fresh response.
            if response is None:
                response = self.gateway.generate_plan(model_id, request)
                if path:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = path.with_suffix(".tmp")
                    temporary.write_text(response.model_dump_json())
                    temporary.replace(path)
            self.input_tokens.append(response.usage.input_tokens)
            self.output_tokens.append(response.usage.output_tokens)
            return response
        finally:
            self.duration_seconds += perf_counter() - start

    def tokens(self, values):
        return (
            sum(values)
            if len(values) == self.attempts
            and values
            and all(value is not None for value in values)
            else None
        )
