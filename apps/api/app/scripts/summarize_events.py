"""Summarize safe application JSON events from stdin; ignore unstructured logs."""

import json
import math
import sys
from collections import Counter

from app.core.observability import CODES, EVENTS


def summarize(lines):
    counts, rejections, states, durations = Counter(), Counter(), Counter(), []
    input_tokens = output_tokens = usage_known = completed = failures = 0
    cost = 0.0
    cost_known = corrections = corrected = 0
    for line in lines:
        try:
            record = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(record, dict) or record.get("schema_version") != 1:
            continue
        name = record.get("event")
        if not isinstance(name, str) or name not in EVENTS:
            continue
        counts[name] += 1
        if name == "plan.rejected":
            code = record.get("error_code")
            rejections[code if isinstance(code, str) and code in CODES else "UNKNOWN"] += 1
            corrections += record.get("generation_attempt") == 1
        if name == "plan.accepted" and record.get("correction") is True:
            corrected += 1
        if name == "analysis.state":
            status = record.get("status")
            if isinstance(status, str) and status in {
                "QUEUED",
                "PROCESSING",
                "SUCCEEDED",
                "FAILED",
                "NEEDS_CLARIFICATION",
            }:
                states[status] += 1
        if name == "model.failed":
            failures += 1
        if name == "model.completed":
            completed += 1
            duration = record.get("duration_ms")
            if type(duration) in (float, int) and math.isfinite(duration) and duration >= 0:
                durations.append(duration)
            incoming, outgoing = record.get("input_tokens"), record.get("output_tokens")
            if type(incoming) is int and type(outgoing) is int and incoming >= 0 and outgoing >= 0:
                usage_known += 1
                input_tokens += incoming
                output_tokens += outgoing
            estimate = record.get("estimated_response_cost_usd")
            if type(estimate) in (float, int) and math.isfinite(estimate) and estimate >= 0:
                cost_known += 1
                cost += estimate
    durations.sort()

    def percentile(fraction):
        return durations[max(0, math.ceil(len(durations) * fraction) - 1)] if durations else None

    return {
        "events": dict(counts),
        "analysis_state_events": dict(states),
        "rejection_codes": dict(rejections),
        "correction_requests": corrections,
        "correction_successes": corrected,
        "model_responses": completed,
        "model_failures": failures,
        "model_latency_p50_ms": percentile(0.5),
        "model_latency_p95_ms": percentile(0.95),
        "responses_with_usage": usage_known,
        "known_input_tokens": input_tokens,
        "known_output_tokens": output_tokens,
        "responses_with_cost_estimate": cost_known,
        "known_estimated_response_cost_usd": round(cost, 10) if cost_known else None,
    }


def main():
    print(json.dumps(summarize(sys.stdin), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
