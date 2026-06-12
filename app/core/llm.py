"""Thin LLM client wrapper.

If ANTHROPIC_API_KEY is set, calls Claude via the official SDK. Otherwise
falls back to a deterministic heuristic response so the agent works
offline (CI, demos, and reviewers without an API key).

Two entry points:

- `call_llm(prompt, node=...)` — free-form text response. Used by log and
  metric nodes where the parsed output is best-effort.
- `call_llm_tool(prompt, node=..., tool=...)` — forces the model to call a
  named tool with a strict JSON-Schema input. Used by the synthesizer where
  the category MUST be one of a fixed enum.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.core.config import get_settings
from app.core.metrics import agent_llm_calls_total

settings = get_settings()


_CATEGORY_KEYWORDS = {
    "db_pool_exhaustion": [
        "connection pool", "pool exhaust", "db wait", "connections", "pool_size",
        "too many connections",
    ],
    "memory_leak": ["oom", "out of memory", "heap", "memory leak", "rss"],
    "timeout_cascade": ["timeout", "deadline exceeded", "upstream", "503", "504"],
    "misconfiguration": ["config", "env var", "missing", "invalid", "feature flag"],
    "dependency_failure": [
        "downstream", "third-party", "dns", "tls", "certificate", "stripe", "kafka",
    ],
}


def heuristic_category(text: str) -> tuple[str, int]:
    """Return the (best_category, signal_count) for a body of text.

    Exposed so the synthesizer can pass the keyword classifier's guess to
    Claude as a prior — cheap, deterministic, and useful as a tie-breaker.
    """
    lowered = text.lower()
    scores = {cat: sum(1 for kw in kws if kw in lowered) for cat, kws in _CATEGORY_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return (best if scores[best] > 0 else "misconfiguration", scores[best])


def _heuristic_response(prompt: str) -> str:
    best, signals = heuristic_category(prompt)
    confidence = round(min(0.95, 0.55 + 0.08 * signals), 2)
    return json.dumps(
        {
            "root_cause_category": best,
            "root_cause": f"Likely {best.replace('_', ' ')} based on observed signals.",
            "confidence": confidence,
            "triggered_by": "Recent deployment correlated with anomaly onset.",
            "evidence": [
                "Error rate increased sharply within the incident window.",
                "Latency p95 deviates from baseline.",
            ],
            "suggested_fix": "Roll back the suspected deployment or apply targeted mitigation.",
        }
    )


def call_llm(prompt: str, *, node: str, system: str | None = None) -> str:
    agent_llm_calls_total.labels(node=node, model=settings.llm_model).inc()
    if not settings.anthropic_api_key:
        return _heuristic_response(prompt)
    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=settings.anthropic_api_key)
        msg = client.messages.create(
            model=settings.llm_model,
            max_tokens=1024,
            temperature=0,
            system=system or "You are an expert SRE incident investigator. Always reply with valid JSON.",
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in msg.content if getattr(block, "type", None) == "text")
    except Exception:
        return _heuristic_response(prompt)


def call_llm_tool(
    prompt: str,
    *,
    node: str,
    tool: dict[str, Any],
    system: str | None = None,
) -> dict[str, Any]:
    """Force the model to call a named tool. Returns its parsed input dict.

    `tool` is a single Anthropic tool spec: {"name", "description",
    "input_schema"}. We set tool_choice to force the model to invoke it.

    Falls back to the heuristic responder (and best-effort enum coercion)
    when no API key is set or the call fails.
    """
    agent_llm_calls_total.labels(node=node, model=settings.llm_model).inc()
    if not settings.anthropic_api_key:
        return _heuristic_tool_response(prompt, tool)
    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=settings.anthropic_api_key)
        msg = client.messages.create(
            model=settings.llm_model,
            max_tokens=1024,
            temperature=0,
            system=system or "You are an expert SRE incident investigator.",
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in msg.content:
            if getattr(block, "type", None) == "tool_use" and block.name == tool["name"]:
                return dict(block.input)
        return _heuristic_tool_response(prompt, tool)
    except Exception:
        return _heuristic_tool_response(prompt, tool)


def _heuristic_tool_response(prompt: str, tool: dict[str, Any]) -> dict[str, Any]:
    raw = _heuristic_response(prompt)
    parsed = extract_json(raw)
    # When the synthesizer passes an explicit "suggests category: X" hint
    # (computed from clean signals — not the full prompt), trust it. The
    # full prompt now contains few-shot examples that name every category,
    # which would confuse the bare keyword scorer.
    hint_match = re.search(r"suggests category:\s*([a-z_]+)", prompt)
    if hint_match:
        parsed["root_cause_category"] = hint_match.group(1)
    # Coerce the category to the tool's enum if one is declared.
    schema = tool.get("input_schema", {})
    category_field = schema.get("properties", {}).get("root_cause_category", {})
    enum_values = category_field.get("enum")
    if enum_values and parsed.get("root_cause_category") not in enum_values:
        parsed["root_cause_category"] = enum_values[0]
    return parsed


def extract_json(text: str) -> dict[str, Any]:
    """Best-effort JSON extraction from an LLM response."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {}
