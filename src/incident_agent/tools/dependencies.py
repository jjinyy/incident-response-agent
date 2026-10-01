"""Dependency health from client spans."""

from __future__ import annotations

import math
from dataclasses import dataclass

from incident_agent.tools.metrics import TimeRange
from incident_agent.world.telemetry import WorldSlice


@dataclass(frozen=True)
class DependencyHealth:
    evidence_id: str
    service_name: str
    dependency: str
    call_count: int
    error_rate: float
    latency_p95_ms: float


def get_dependency_health(
    world: WorldSlice, service_name: str, time_range: TimeRange
) -> list[DependencyHealth]:
    grouped: dict[str, list[int]] = {}
    errors: dict[str, int] = {}
    for span in world.spans:
        if span.service_name != service_name or span.dependency is None:
            continue
        if not (time_range.start <= span.start_time < time_range.end):
            continue
        grouped.setdefault(span.dependency, []).append(span.duration_ms)
        errors[span.dependency] = errors.get(span.dependency, 0) + (span.status != "ok")
    records = []
    for dependency, durations in sorted(grouped.items()):
        records.append(
            DependencyHealth(
                evidence_id=f"dependency:{service_name}:{dependency}:{time_range.start.isoformat()}",
                service_name=service_name,
                dependency=dependency,
                call_count=len(durations),
                error_rate=errors[dependency] / len(durations),
                latency_p95_ms=_p95(durations),
            )
        )
    return records


def _p95(values: list[int]) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return float(ordered[index])
