"""Checkout traces and the operational records derived from them."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

STATUSES = ("ok", "error", "timeout")

BASE_VERSIONS = {
    "api-gateway": "v1.4.0",
    "auth-service": "v1.1.0",
    "order-service": "v3.2.1",
    "payment-service": "v2.14.2",
    "inventory-service": "v1.8.0",
    "notification-service": "v0.9.4",
}


@dataclass
class Span:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    request_id: str
    service_name: str
    operation: str
    start_time: datetime
    duration_ms: int
    status: str
    dependency: str | None = None
    attributes: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown status: {self.status}")
        if self.duration_ms < 0:
            raise ValueError("duration_ms must be >= 0")
        if self.start_time.tzinfo is None:
            raise ValueError("start_time must be timezone-aware")

    @property
    def end_time(self) -> datetime:
        return self.start_time + timedelta(milliseconds=self.duration_ms)


@dataclass
class Deployment:
    service_name: str
    version: str
    deployed_at: datetime
    status: str = "succeeded"


@dataclass
class ConfigChange:
    service_name: str
    key: str
    old_value: str
    new_value: str
    changed_at: datetime
    change_type: str


@dataclass
class LogEvent:
    service_name: str
    timestamp: datetime
    level: str
    message: str
    trace_id: str
    request_id: str
    span_id: str


@dataclass
class MetricPoint:
    service_name: str
    name: str
    bucket_start: datetime
    value: float
    dependency: str | None = None


@dataclass
class Runbook:
    runbook_id: str
    title: str
    body: str


@dataclass
class HistoricalIncident:
    incident_id: str
    title: str
    summary: str
    root_cause_label: str


@dataclass
class WorldSlice:
    spans: list[Span]
    deployments: list[Deployment] = field(default_factory=list)
    config_changes: list[ConfigChange] = field(default_factory=list)
    logs: list[LogEvent] = field(default_factory=list)
    metrics: list[MetricPoint] = field(default_factory=list)
    runbooks: list[Runbook] = field(default_factory=list)
    incidents: list[HistoricalIncident] = field(default_factory=list)

    def by_trace(self) -> dict[str, list[Span]]:
        grouped: dict[str, list[Span]] = defaultdict(list)
        for span in self.spans:
            grouped[span.trace_id].append(span)
        return dict(grouped)


def _span(
    *,
    trace_id: str,
    span_id: str,
    parent_span_id: str | None,
    request_id: str,
    service_name: str,
    operation: str,
    start_time: datetime,
    duration_ms: int,
    dependency: str | None = None,
) -> Span:
    return Span(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        request_id=request_id,
        service_name=service_name,
        operation=operation,
        start_time=start_time,
        duration_ms=duration_ms,
        status="ok",
        dependency=dependency,
        attributes={"deployment_version": BASE_VERSIONS[service_name]},
    )


def _duration_covering(start: datetime, children: list[Span], tail_ms: int) -> int:
    """Parent duration includes every child and a little work after the last one."""
    if not children:
        return tail_ms
    last_end = max(child.end_time for child in children)
    covered_ms = int((last_end - start).total_seconds() * 1000)
    return covered_ms + tail_ms


def checkout_trace(index: int, start: datetime, include_cache: bool = False) -> list[Span]:
    """Build one successful checkout trace.

    api-gateway POST /checkout
      order-service CreateOrder
        order-service SELECT orders          dependency=postgres
        payment-service Authorize
          payment-service POST /charges      dependency=paygate
      inventory-service ReserveStock
    """
    if start.tzinfo is None:
        raise ValueError("start must be timezone-aware")

    trace_id = f"trace-{index:04d}"
    request_id = f"req-{index:04d}"

    postgres = _span(
        trace_id=trace_id,
        span_id=f"{trace_id}-postgres",
        parent_span_id=f"{trace_id}-order",
        request_id=request_id,
        service_name="order-service",
        operation="SELECT orders",
        start_time=start + timedelta(milliseconds=6),
        duration_ms=8,
        dependency="postgres",
    )
    paygate = _span(
        trace_id=trace_id,
        span_id=f"{trace_id}-paygate",
        parent_span_id=f"{trace_id}-payment",
        request_id=request_id,
        service_name="payment-service",
        operation="POST /charges",
        start_time=start + timedelta(milliseconds=20),
        duration_ms=40,
        dependency="paygate",
    )
    payment_start = start + timedelta(milliseconds=16)
    payment = _span(
        trace_id=trace_id,
        span_id=f"{trace_id}-payment",
        parent_span_id=f"{trace_id}-order",
        request_id=request_id,
        service_name="payment-service",
        operation="Authorize",
        start_time=payment_start,
        duration_ms=_duration_covering(payment_start, [paygate], tail_ms=6),
    )
    order_start = start + timedelta(milliseconds=2)
    order_children = [postgres, payment]
    redis = None
    if include_cache:
        redis = _span(
            trace_id=trace_id,
            span_id=f"{trace_id}-redis",
            parent_span_id=f"{trace_id}-order",
            request_id=request_id,
            service_name="order-service",
            operation="GET cart",
            start_time=start + timedelta(milliseconds=14),
            duration_ms=4,
            dependency="redis",
        )
        order_children.append(redis)
    order = _span(
        trace_id=trace_id,
        span_id=f"{trace_id}-order",
        parent_span_id=f"{trace_id}-gateway",
        request_id=request_id,
        service_name="order-service",
        operation="CreateOrder",
        start_time=order_start,
        duration_ms=_duration_covering(order_start, order_children, tail_ms=6),
    )
    inventory = _span(
        trace_id=trace_id,
        span_id=f"{trace_id}-inventory",
        parent_span_id=f"{trace_id}-gateway",
        request_id=request_id,
        service_name="inventory-service",
        operation="ReserveStock",
        start_time=start + timedelta(milliseconds=4),
        duration_ms=10,
    )
    gateway = _span(
        trace_id=trace_id,
        span_id=f"{trace_id}-gateway",
        parent_span_id=None,
        request_id=request_id,
        service_name="api-gateway",
        operation="POST /checkout",
        start_time=start,
        duration_ms=_duration_covering(start, [order, inventory], tail_ms=8),
    )
    spans = [gateway, order, postgres, payment, paygate, inventory]
    if redis is not None:
        spans.append(redis)
    check_trace_consistency(spans)
    return spans


def generate_healthy_checkouts(
    count: int,
    start: datetime | None = None,
    spacing_seconds: int = 1,
    include_cache: bool = False,
) -> WorldSlice:
    if count < 1:
        raise ValueError("count must be >= 1")
    origin = start or datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc)
    spans: list[Span] = []
    for index in range(count):
        spans.extend(
            checkout_trace(
                index,
                origin + timedelta(seconds=index * spacing_seconds),
                include_cache=include_cache,
            )
        )
    return WorldSlice(spans=spans)


def check_trace_consistency(spans: list[Span]) -> None:
    """Raise ValueError when parent links or time windows disagree."""
    if not spans:
        raise ValueError("trace is empty")

    by_id: dict[str, Span] = {}
    for span in spans:
        if span.span_id in by_id:
            raise ValueError(f"duplicate span_id: {span.span_id}")
        by_id[span.span_id] = span

    roots = [span for span in spans if span.parent_span_id is None]
    if len(roots) != 1:
        raise ValueError(f"expected one root span, found {len(roots)}")

    trace_ids = {span.trace_id for span in spans}
    if len(trace_ids) != 1:
        raise ValueError("spans in one trace must share trace_id")
    request_ids = {span.request_id for span in spans}
    if len(request_ids) != 1:
        raise ValueError("spans in one trace must share request_id")
    if roots[0].trace_id == roots[0].request_id:
        raise ValueError("trace_id and request_id must differ")

    for span in spans:
        if span.parent_span_id is None:
            continue
        parent = by_id.get(span.parent_span_id)
        if parent is None:
            raise ValueError(f"missing parent {span.parent_span_id}")
        if parent.trace_id != span.trace_id:
            raise ValueError("parent is in a different trace")
        if span.start_time < parent.start_time or span.end_time > parent.end_time:
            raise ValueError(
                f"{span.span_id} falls outside parent {parent.span_id}"
            )
        _reject_cycles(span, by_id)


def _reject_cycles(span: Span, by_id: dict[str, Span]) -> None:
    seen = {span.span_id}
    current = span
    while current.parent_span_id is not None:
        if current.parent_span_id in seen:
            raise ValueError(f"cycle at {current.parent_span_id}")
        seen.add(current.parent_span_id)
        current = by_id[current.parent_span_id]
