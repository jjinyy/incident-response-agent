"""Find traces that contain a matching span."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from incident_agent.tools.metrics import TimeRange
from incident_agent.world.telemetry import Span, WorldSlice


@dataclass(frozen=True)
class TraceQuery:
    service_name: str
    time_range: TimeRange
    status: str | None = None
    operation: str | None = None
    dependency: str | None = None
    min_duration_ms: int | None = None
    limit: int = 20

    def __post_init__(self) -> None:
        if not self.service_name:
            raise ValueError("service_name must not be empty")
        if self.limit < 1:
            raise ValueError("limit must be >= 1")
        if self.min_duration_ms is not None and self.min_duration_ms < 0:
            raise ValueError("min_duration_ms must be >= 0")


@dataclass(frozen=True)
class TraceRecord:
    evidence_id: str
    trace_id: str
    request_id: str
    root_service: str
    root_operation: str
    root_status: str
    matched_span_id: str
    matched_operation: str
    matched_status: str
    matched_dependency: str | None
    start_time: datetime


def search_traces(world: WorldSlice, query: TraceQuery) -> list[TraceRecord]:
    """Return one row per trace that has a span matching the filters."""
    grouped: dict[str, list[Span]] = {}
    for span in world.spans:
        grouped.setdefault(span.trace_id, []).append(span)

    records: list[TraceRecord] = []
    for trace_id, spans in grouped.items():
        matched = [span for span in spans if _matches(span, query)]
        if not matched:
            continue
        matched.sort(key=lambda span: (span.start_time, span.span_id))
        hit = matched[0]
        root = next(span for span in spans if span.parent_span_id is None)
        records.append(
            TraceRecord(
                evidence_id=f"trace:{trace_id}",
                trace_id=trace_id,
                request_id=root.request_id,
                root_service=root.service_name,
                root_operation=root.operation,
                root_status=root.status,
                matched_span_id=hit.span_id,
                matched_operation=hit.operation,
                matched_status=hit.status,
                matched_dependency=hit.dependency,
                start_time=hit.start_time,
            )
        )
    records.sort(key=lambda record: (record.start_time, record.trace_id))
    return records[: query.limit]


def _matches(span: Span, query: TraceQuery) -> bool:
    if span.service_name != query.service_name:
        return False
    if not (query.time_range.start <= span.start_time < query.time_range.end):
        return False
    if query.status is not None and span.status != query.status:
        return False
    if query.operation is not None and span.operation != query.operation:
        return False
    if query.dependency is not None and span.dependency != query.dependency:
        return False
    if query.min_duration_ms is not None and span.duration_ms < query.min_duration_ms:
        return False
    return True


@dataclass(frozen=True)
class SpanRecord:
    evidence_id: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    request_id: str
    service_name: str
    operation: str
    start_time: datetime
    duration_ms: int
    status: str
    dependency: str | None


def get_trace(world: WorldSlice, trace_id: str) -> list[SpanRecord]:
    """Return every span in one trace, parent before children."""
    if not trace_id:
        raise ValueError("trace_id must not be empty")
    spans = [span for span in world.spans if span.trace_id == trace_id]
    if not spans:
        raise ValueError(f"unknown trace: {trace_id}")
    ordered = _tree_order(spans)
    return [
        SpanRecord(
            evidence_id=f"span:{span.span_id}",
            trace_id=span.trace_id,
            span_id=span.span_id,
            parent_span_id=span.parent_span_id,
            request_id=span.request_id,
            service_name=span.service_name,
            operation=span.operation,
            start_time=span.start_time,
            duration_ms=span.duration_ms,
            status=span.status,
            dependency=span.dependency,
        )
        for span in ordered
    ]


def _tree_order(spans: list[Span]) -> list[Span]:
    children: dict[str | None, list[Span]] = {}
    for span in spans:
        children.setdefault(span.parent_span_id, []).append(span)
    ordered: list[Span] = []

    def walk(parent_id: str | None) -> None:
        kids = sorted(children.get(parent_id, []), key=lambda span: (span.start_time, span.span_id))
        for span in kids:
            ordered.append(span)
            walk(span.span_id)

    walk(None)
    if len(ordered) != len(spans):
        raise ValueError("trace has a broken parent link")
    return ordered
