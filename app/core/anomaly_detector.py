"""Lightweight anomaly detection on metric time-series.

Used by the metric correlator node to find spike onsets without burning LLM
context on raw points.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import mean, pstdev


@dataclass
class Anomaly:
    metric: str
    onset: datetime
    peak_value: float
    baseline: float
    z_score: float

    def as_dict(self) -> dict:
        return {
            "metric": self.metric,
            "onset": self.onset.isoformat(),
            "peak_value": round(self.peak_value, 3),
            "baseline": round(self.baseline, 3),
            "z_score": round(self.z_score, 2),
        }


def detect_anomalies(
    series: list[tuple[datetime, float]],
    metric_name: str,
    z_threshold: float = 2.5,
) -> Anomaly | None:
    if len(series) < 6:
        return None
    values = [v for _, v in series]
    baseline = mean(values[: max(3, len(values) // 3)])
    std = pstdev(values) or 1e-9
    for ts, val in series:
        z = (val - baseline) / std
        if z >= z_threshold:
            peak = max(values)
            return Anomaly(metric=metric_name, onset=ts, peak_value=peak, baseline=baseline, z_score=z)
    return None
