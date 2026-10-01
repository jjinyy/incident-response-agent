"""Read service metrics from a world slice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from incident_agent.world.telemetry import WorldSlice


@dataclass(frozen=True)
class TimeRange:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("time range must be timezone-aware")
        if self.end <= self.start:
            raise ValueError("time range end must be after start")


@dataclass(frozen=True)
class MetricQuery:
    service_name: str
    metric_names: tuple[str, ...]
    time_range: TimeRange

    def __post_init__(self) -> None:
        if not self.metric_names:
            raise ValueError("metric_names must not be empty")


@dataclass(frozen=True)
class MetricRecord:
    evidence_id: str
    service_name: str
    name: str
    bucket_start: datetime
    value: float
    dependency: str | None = None


def get_service_metrics(world: WorldSlice, query: MetricQuery) -> list[MetricRecord]:
    """Return metric buckets inside the half-open range [start, end)."""
    names = set(query.metric_names)
    records = [
        MetricRecord(
            evidence_id=_evidence_id(point.service_name, point.name, point.bucket_start, point.dependency),
            service_name=point.service_name,
            name=point.name,
            bucket_start=point.bucket_start,
            value=point.value,
            dependency=point.dependency,
        )
        for point in world.metrics
        if point.service_name == query.service_name
        and point.name in names
        and query.time_range.start <= point.bucket_start < query.time_range.end
    ]
    return sorted(records, key=lambda record: (record.bucket_start, record.name, record.dependency or ""))


def _evidence_id(service: str, name: str, bucket_start: datetime, dependency: str | None) -> str:
    suffix = dependency or "-"
    return f"metric:{service}:{name}:{suffix}:{bucket_start.isoformat()}"
