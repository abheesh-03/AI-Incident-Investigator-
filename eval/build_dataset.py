"""Generate eval/dataset/incidents.json from the synthetic generator so the
labels stay in lock-step with the seeded data."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.synth import generate_incidents

OUT = Path(__file__).parent / "dataset" / "incidents.json"


def build() -> None:
    incidents = generate_incidents(n=50)
    payload = [
        {
            "external_id": inc.external_id,
            "title": inc.title,
            "affected_services": inc.services,
            "started_at": inc.started_at.isoformat(),
            "ended_at": inc.ended_at.isoformat(),
            "expected_root_cause_category": inc.category,
            "expected_root_cause": inc.expected_root_cause,
            "expected_fix": inc.expected_fix,
        }
        for inc in incidents
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {len(payload)} labeled incidents to {OUT}")


if __name__ == "__main__":
    build()
