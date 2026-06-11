from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime

from app.agent.state import InvestigationState
from app.core.anomaly_detector import detect_anomalies
from app.core.llm import call_llm, extract_json
from app.core.metrics import agent_node_duration_seconds

NODE = "metric_correlator"

PROMPT = """You are correlating metric anomalies with log patterns and recent deployments.

Log analysis:
- Dominant error pattern: {dominant_pattern}
- Anomaly onset: {anomaly_onset}
- Initial hypothesis: {hypothesis}

Detected metric anomalies:
{anomalies}

Recent deployments in window:
{deployments}

Answer in strict JSON only:
{{"correlated_metrics": ["..."], "deployment_link": "...", "refined_hypothesis": "...", "confidence_hint": 0.0}}
"""


def _parse_ts(ts) -> datetime:
    if isinstance(ts, datetime):
        return ts
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def metric_correlator_node(state: InvestigationState) -> InvestigationState:
    start = time.perf_counter()
    metrics = state.get("metrics", [])
    deployments = state.get("deployments", [])

    series_by_metric: dict[tuple[str, str], list[tuple[datetime, float]]] = defaultdict(list)
    for m in metrics:
        key = (m.get("service", ""), m.get("name", ""))
        series_by_metric[key].append((_parse_ts(m["timestamp"]), float(m["value"])))

    anomalies = []
    for (service, name), series in series_by_metric.items():
        series.sort(key=lambda x: x[0])
        anomaly = detect_anomalies(series, f"{service}:{name}")
        if anomaly:
            anomalies.append(anomaly.as_dict())

    deployment_descriptions = "\n".join(
        f"- {d.get('timestamp')} | {d.get('service')} | {d.get('version')} | {d.get('description')}"
        for d in deployments
    ) or "- (no deployments in window)"

    anomaly_text = "\n".join(f"- {a}" for a in anomalies) or "- (no significant anomalies)"
    log_analysis = state.get("log_analysis", {})
    prompt = PROMPT.format(
        dominant_pattern=log_analysis.get("dominant_pattern", ""),
        anomaly_onset=log_analysis.get("anomaly_onset", ""),
        hypothesis=log_analysis.get("root_cause_hypothesis", ""),
        anomalies=anomaly_text,
        deployments=deployment_descriptions,
    )
    raw = call_llm(prompt, node=NODE)
    parsed = extract_json(raw) or {}

    analysis = {
        "anomalies": anomalies,
        "correlated_metrics": parsed.get("correlated_metrics", [a["metric"] for a in anomalies]),
        "deployment_link": parsed.get(
            "deployment_link",
            deployments[0].get("version") if deployments else "no deployment link identified",
        ),
        "refined_hypothesis": parsed.get(
            "refined_hypothesis", log_analysis.get("root_cause_hypothesis", "")
        ),
        "confidence_hint": float(parsed.get("confidence_hint", 0.6) or 0.6),
    }

    elapsed = time.perf_counter() - start
    agent_node_duration_seconds.labels(node=NODE).observe(elapsed)
    trace = list(state.get("trace") or [])
    trace.append({"node": NODE, "duration_s": round(elapsed, 3), "output": analysis})

    return {**state, "metric_analysis": analysis, "trace": trace}
