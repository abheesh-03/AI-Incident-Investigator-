from __future__ import annotations

import time
from collections import Counter

from app.agent.state import InvestigationState
from app.core.llm import call_llm, extract_json
from app.core.metrics import agent_node_duration_seconds

NODE = "log_analyzer"

PROMPT = """You are analyzing logs from a production incident.

Incident window: {started_at} to {ended_at}
Affected services: {services}

Error-level log message samples (most frequent first):
{error_samples}

Total log volume: {total_logs} entries
Error count: {error_count}
Warn count: {warn_count}

Identify:
1. The dominant error pattern (1-2 sentences).
2. The anomaly_onset timestamp (when errors started spiking) — pick the earliest of the listed error timestamps.
3. An initial root_cause_hypothesis.

Reply with strict JSON only:
{{"dominant_pattern": "...", "anomaly_onset": "...", "root_cause_hypothesis": "..."}}
"""


def log_analyzer_node(state: InvestigationState) -> InvestigationState:
    start = time.perf_counter()
    logs = state.get("logs", [])
    errors = [log for log in logs if log.get("level", "").upper() in {"ERROR", "FATAL"}]
    warns = [log for log in logs if log.get("level", "").upper() == "WARN"]

    pattern_counter = Counter()
    for log in errors:
        msg = (log.get("message") or "")[:200]
        pattern_counter[msg] += 1
    top_patterns = pattern_counter.most_common(5)
    error_samples = "\n".join(f"- ({count}x) {msg}" for msg, count in top_patterns) or "- (no errors)"

    onset_guess = errors[0]["timestamp"] if errors else state.get("started_at")

    prompt = PROMPT.format(
        started_at=state.get("started_at"),
        ended_at=state.get("ended_at"),
        services=", ".join(state.get("affected_services") or []),
        error_samples=error_samples,
        total_logs=len(logs),
        error_count=len(errors),
        warn_count=len(warns),
    )
    raw = call_llm(prompt, node=NODE)
    parsed = extract_json(raw) or {
        "dominant_pattern": top_patterns[0][0] if top_patterns else "no dominant pattern",
        "anomaly_onset": str(onset_guess),
        "root_cause_hypothesis": "Unknown — insufficient signal in logs.",
    }

    analysis = {
        "dominant_pattern": parsed.get("dominant_pattern", ""),
        "anomaly_onset": parsed.get("anomaly_onset", str(onset_guess)),
        "root_cause_hypothesis": parsed.get("root_cause_hypothesis", ""),
        "error_count": len(errors),
        "warn_count": len(warns),
        "total_logs": len(logs),
        "top_patterns": [{"message": m, "count": c} for m, c in top_patterns],
    }

    elapsed = time.perf_counter() - start
    agent_node_duration_seconds.labels(node=NODE).observe(elapsed)
    trace = list(state.get("trace") or [])
    trace.append({"node": NODE, "duration_s": round(elapsed, 3), "output": analysis})

    return {**state, "log_analysis": analysis, "trace": trace}
