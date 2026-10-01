"""Service list and health from server spans."""

from __future__ import annotations

import math
from dataclasses import dataclass

from incident_agent.tools.metrics import TimeRange
from incident_agent.world.telemetry import Span, WorldSlice


@dataclass(frozen=True)
class ServiceRecord:
    service_name: str
    dependencies: tuple[str, ...]


@dataclass(frozen=True)
class HealthRecord:
    evidence_id: str
    service_name: str
    request_count: int
    error_rate: float
    latency_p95_ms: float


def list_services(world: WorldSlice) -> list[ServiceRecord]:
    dependencies: dict[str, set[str]] = {}
    for span in world.spans:
        dependencies.setdefault(span.service_name, set())
        if span.dependency:
            dependencies[span.service_name].add(span.dependency)
    return [
        ServiceRecord(service_name=name, dependencies=tuple(sorted(deps)))
        for name, deps in sorted(dependencies.items())
    ]


def get_service_health(world: WorldSlice, service_name: str, time_range: TimeRange) -> HealthRecord:
    spans = [
        span
        for span in world.spans
        if span.service_name == service_name
        and span.dependency is None
        and time_range.start <= span.start_time < time_range.end
    ]
    if not spans:
        raise ValueError(f"no server spans for {service_name} in range")
    errors = sum(1 for span in spans if span.status != "ok")
    return HealthRecord(
        evidence_id=f"health:{service_name}:{time_range.start.isoformat()}",
        service_name=service_name,
        request_count=len(spans),
        error_rate=errors / len(spans),
        latency_p95_ms=_p95([span.duration_ms for span in spans]),
    )


def _p95(values: list[int]) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return float(ordered[index])
