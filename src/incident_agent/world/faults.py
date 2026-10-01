"""Fault injectors. These are scenario builders, not agent tools."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import datetime, timedelta

from incident_agent.world.telemetry import (
    ConfigChange,
    Deployment,
    LogEvent,
    MetricPoint,
    Span,
    WorldSlice,
    check_trace_consistency,
    checkout_trace,
)


def inject_deployment_regression(
    world: WorldSlice,
    *,
    service: str,
    version: str,
    at: datetime,
    error_rate: float,
    error_type: str,
    seed: int,
) -> WorldSlice:
    """Mark a deploy at `at` and fail that service's later server spans.

    Client spans stay successful, so the failure sits in the service itself.
    Ancestor server spans become errors because the request failed upstream.
    """
    if not 0.0 <= error_rate <= 1.0:
        raise ValueError("error_rate must be between 0 and 1")
    if at.tzinfo is None:
        raise ValueError("at must be timezone-aware")

    spans = _copy_spans(world)
    targets = [
        span
        for span in spans
        if span.service_name == service and span.dependency is None and span.start_time >= at
    ]
    if not targets:
        raise ValueError(f"no server spans for {service} at or after {at.isoformat()}")

    rng = random.Random(seed)
    for span in targets:
        span.attributes["deployment_version"] = version
        if rng.random() < error_rate:
            span.status = "error"
            span.attributes["error_type"] = error_type

    _propagate_to_ancestor_servers(spans)

    for trace_spans in _group(spans).values():
        check_trace_consistency(trace_spans)

    return WorldSlice(
        spans=spans,
        deployments=[
            Deployment(
                service_name=service,
                version=version,
                deployed_at=at,
                status="succeeded",
            )
        ],
        config_changes=list(world.config_changes),
        logs=_logs_for_errors(spans),
        metrics=_error_rate_metrics(spans),
    )


def inject_dependency_latency(
    world: WorldSlice,
    *,
    service: str,
    dependency: str,
    at: datetime,
    added_ms: int,
    timeout_rate: float = 0.0,
    seed: int = 0,
) -> WorldSlice:
    """Slow one downstream call and stretch every ancestor by the same amount.

    The caller's own work stays the same length. No deployment is recorded.
    CPU for the caller stays flat, including after the slowdown starts.
    """
    if added_ms <= 0:
        raise ValueError("added_ms must be positive")
    if not 0.0 <= timeout_rate <= 1.0:
        raise ValueError("timeout_rate must be between 0 and 1")
    if at.tzinfo is None:
        raise ValueError("at must be timezone-aware")

    spans = _copy_spans(world)
    targets = [
        span
        for span in spans
        if span.service_name == service
        and span.dependency == dependency
        and span.start_time >= at
    ]
    if not targets:
        raise ValueError(
            f"no {dependency} spans for {service} at or after {at.isoformat()}"
        )

    rng = random.Random(seed)
    for span in targets:
        span.duration_ms += added_ms
        _add_duration_to_ancestors(span, spans, added_ms)
        if rng.random() < timeout_rate:
            span.status = "timeout"
            span.attributes["error_type"] = "timeout"

    _propagate_to_ancestor_servers(spans)
    for trace_spans in _group(spans).values():
        check_trace_consistency(trace_spans)

    return WorldSlice(
        spans=spans,
        deployments=list(world.deployments),
        config_changes=list(world.config_changes),
        logs=_logs_for_errors(spans),
        metrics=[
            *_error_rate_metrics(spans),
            *_latency_p95_metrics(spans, dependency=dependency),
            *_flat_cpu_metrics(spans, service, value=0.3),
        ],
    )


def inject_bad_configuration(
    world: WorldSlice,
    *,
    service: str,
    at: datetime,
    key: str,
    old_value: str,
    new_value: str,
    change_type: str,
    error_type: str,
    error_rate: float = 1.0,
    seed: int = 0,
    deployed_version: str | None = None,
    deployed_at: datetime | None = None,
) -> WorldSlice:
    """Fail server spans after a config change. The running version stays put.

    A successful deployment may be recorded earlier. Errors line up with the
    config change, not with that deploy.
    """
    if change_type not in ("env", "feature_flag"):
        raise ValueError("change_type must be env or feature_flag")
    if not 0.0 <= error_rate <= 1.0:
        raise ValueError("error_rate must be between 0 and 1")
    if at.tzinfo is None:
        raise ValueError("at must be timezone-aware")
    if (deployed_at is None) != (deployed_version is None):
        raise ValueError("deployed_at and deployed_version must be set together")
    if deployed_at is not None and deployed_at >= at:
        raise ValueError("deployment must be earlier than the config change")

    spans = _copy_spans(world)
    targets = [
        span
        for span in spans
        if span.service_name == service and span.dependency is None and span.start_time >= at
    ]
    if not targets:
        raise ValueError(f"no server spans for {service} at or after {at.isoformat()}")

    rng = random.Random(seed)
    for span in targets:
        if rng.random() < error_rate:
            span.status = "error"
            span.attributes["error_type"] = error_type

    _propagate_to_ancestor_servers(spans)
    for trace_spans in _group(spans).values():
        check_trace_consistency(trace_spans)

    deployments = list(world.deployments)
    if deployed_at is not None and deployed_version is not None:
        deployments.append(
            Deployment(
                service_name=service,
                version=deployed_version,
                deployed_at=deployed_at,
                status="succeeded",
            )
        )

    return WorldSlice(
        spans=spans,
        deployments=deployments,
        config_changes=[
            *world.config_changes,
            ConfigChange(
                service_name=service,
                key=key,
                old_value=old_value,
                new_value=new_value,
                changed_at=at,
                change_type=change_type,
            ),
        ],
        logs=_logs_for_errors(spans),
        metrics=_error_rate_metrics(spans),
    )


def inject_connection_pool_exhaustion(
    world: WorldSlice,
    *,
    service: str,
    at: datetime,
    added_ms: int = 400,
) -> WorldSlice:
    """Time out postgres calls after the pool fills. CPU stays flat."""
    if added_ms <= 0:
        raise ValueError("added_ms must be positive")
    if at.tzinfo is None:
        raise ValueError("at must be timezone-aware")

    spans = _copy_spans(world)
    targets = [
        span
        for span in spans
        if span.service_name == service
        and span.dependency == "postgres"
        and span.start_time >= at
    ]
    if not targets:
        raise ValueError(f"no postgres spans for {service} at or after {at.isoformat()}")

    for span in targets:
        span.duration_ms += added_ms
        _add_duration_to_ancestors(span, spans, added_ms)
        span.status = "timeout"
        span.attributes["error_type"] = "connection_pool_timeout"

    _propagate_to_ancestor_servers(spans)
    for trace_spans in _group(spans).values():
        check_trace_consistency(trace_spans)

    return WorldSlice(
        spans=spans,
        deployments=list(world.deployments),
        config_changes=list(world.config_changes),
        logs=_logs_for_errors(spans),
        metrics=[
            *_error_rate_metrics(spans),
            *_step_metric(spans, service, "db_pool_usage", at, before=0.4, after=1.0),
            *_flat_cpu_metrics(spans, service, value=0.3),
        ],
    )


def inject_traffic_spike(
    world: WorldSlice,
    *,
    service: str,
    at: datetime,
    extra_requests: int,
    error_rate: float = 1.0,
    seed: int = 0,
) -> WorldSlice:
    """Add requests after `at` and fail that service when it saturates.

    Dependencies stay healthy. No deployment or config change is recorded.
    """
    if extra_requests < 1:
        raise ValueError("extra_requests must be >= 1")
    if not 0.0 <= error_rate <= 1.0:
        raise ValueError("error_rate must be between 0 and 1")
    if at.tzinfo is None:
        raise ValueError("at must be timezone-aware")

    spans = _copy_spans(world)
    for offset in range(extra_requests):
        spans.extend(checkout_trace(10_000 + offset, at + timedelta(seconds=offset)))

    targets = [
        span
        for span in spans
        if span.service_name == service and span.dependency is None and span.start_time >= at
    ]
    if not targets:
        raise ValueError(f"no server spans for {service} at or after {at.isoformat()}")

    rng = random.Random(seed)
    for span in targets:
        if rng.random() < error_rate:
            span.status = "error"
            span.attributes["error_type"] = "saturated"

    _propagate_to_ancestor_servers(spans)
    for trace_spans in _group(spans).values():
        check_trace_consistency(trace_spans)

    return WorldSlice(
        spans=spans,
        deployments=list(world.deployments),
        config_changes=list(world.config_changes),
        logs=_logs_for_errors(spans),
        metrics=[
            *_error_rate_metrics(spans),
            *_request_rate_metrics(spans, service),
            *_step_metric(spans, service, "cpu_ratio", at, before=0.3, after=0.95),
            *_step_metric(spans, service, "memory_ratio", at, before=0.4, after=0.93),
        ],
    )


def inject_edge_errors(
    world: WorldSlice,
    *,
    service: str,
    at: datetime,
    error_type: str,
    error_rate: float = 1.0,
    seed: int = 0,
    attribute_key: str | None = None,
    attribute_value: str | None = None,
) -> WorldSlice:
    """Fail one service's own server spans. Child calls stay successful."""
    if not 0.0 <= error_rate <= 1.0:
        raise ValueError("error_rate must be between 0 and 1")
    if at.tzinfo is None:
        raise ValueError("at must be timezone-aware")
    spans = _copy_spans(world)
    targets = [
        span
        for span in spans
        if span.service_name == service and span.dependency is None and span.start_time >= at
    ]
    if not targets:
        raise ValueError(f"no server spans for {service} at or after {at.isoformat()}")
    rng = random.Random(seed)
    for span in targets:
        if rng.random() < error_rate:
            span.status = "error"
            span.attributes["error_type"] = error_type
            if attribute_key and attribute_value:
                span.attributes[attribute_key] = attribute_value
    for trace_spans in _group(spans).values():
        check_trace_consistency(trace_spans)
    return WorldSlice(
        spans=spans,
        deployments=list(world.deployments),
        config_changes=list(world.config_changes),
        logs=_logs_for_errors(spans),
        metrics=_error_rate_metrics(spans),
    )


def _copy_spans(world: WorldSlice) -> list[Span]:
    return [
        Span(
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
            attributes=dict(span.attributes),
        )
        for span in world.spans
    ]


def _add_duration_to_ancestors(span: Span, spans: list[Span], added_ms: int) -> None:
    by_id = {item.span_id: item for item in spans}
    current = span
    while current.parent_span_id is not None:
        parent = by_id[current.parent_span_id]
        parent.duration_ms += added_ms
        current = parent


def _propagate_to_ancestor_servers(spans: list[Span]) -> None:
    by_id = {span.span_id: span for span in spans}
    for span in spans:
        if span.status == "ok":
            continue
        current = span
        while current.parent_span_id is not None:
            parent = by_id[current.parent_span_id]
            if parent.dependency is None and parent.status == "ok":
                parent.status = "error"
                parent.attributes["error_type"] = "downstream_error"
            current = parent


def _logs_for_errors(spans: list[Span]) -> list[LogEvent]:
    logs: list[LogEvent] = []
    for span in spans:
        if span.status == "ok":
            continue
        error_type = span.attributes.get("error_type", "error")
        logs.append(
            LogEvent(
                service_name=span.service_name,
                timestamp=span.start_time,
                level="error",
                message=f"{error_type} in {span.operation}",
                trace_id=span.trace_id,
                request_id=span.request_id,
                span_id=span.span_id,
            )
        )
    return logs


def _error_rate_metrics(spans: list[Span], bucket_minutes: int = 5) -> list[MetricPoint]:
    origin = min(span.start_time for span in spans)
    buckets: dict[tuple[str, int], list[Span]] = defaultdict(list)
    for span in spans:
        if span.dependency is not None:
            continue
        index = int((span.start_time - origin).total_seconds() // (bucket_minutes * 60))
        buckets[(span.service_name, index)].append(span)

    points: list[MetricPoint] = []
    for (service_name, index), group in sorted(buckets.items()):
        errors = sum(1 for span in group if span.status != "ok")
        points.append(
            MetricPoint(
                service_name=service_name,
                name="error_rate",
                bucket_start=origin + timedelta(minutes=bucket_minutes * index),
                value=errors / len(group),
            )
        )
    return points


def _latency_p95_metrics(spans: list[Span], dependency: str) -> list[MetricPoint]:
    return [
        *_bucket_p95(spans, name="latency_p95_ms", dependency=None),
        *_bucket_p95(spans, name="dependency_latency_p95_ms", dependency=dependency),
    ]


def _bucket_p95(
    spans: list[Span],
    *,
    name: str,
    dependency: str | None,
) -> list[MetricPoint]:
    origin = min(span.start_time for span in spans)
    buckets: dict[tuple[str, int], list[int]] = defaultdict(list)
    for span in spans:
        if span.dependency != dependency:
            continue
        index = int((span.start_time - origin).total_seconds() // 300)
        buckets[(span.service_name, index)].append(span.duration_ms)

    points: list[MetricPoint] = []
    for (service_name, index), durations in sorted(buckets.items()):
        points.append(
            MetricPoint(
                service_name=service_name,
                name=name,
                bucket_start=origin + timedelta(minutes=5 * index),
                value=_p95(durations),
                dependency=dependency,
            )
        )
    return points


def _request_rate_metrics(spans: list[Span], service: str) -> list[MetricPoint]:
    origin = min(span.start_time for span in spans)
    counts: dict[int, int] = defaultdict(int)
    for span in spans:
        if span.service_name != service or span.parent_span_id is not None:
            continue
        index = int((span.start_time - origin).total_seconds() // 300)
        counts[index] += 1
    return [
        MetricPoint(
            service_name=service,
            name="request_rate",
            bucket_start=origin + timedelta(minutes=5 * index),
            value=count / 5,
        )
        for index, count in sorted(counts.items())
    ]


def _step_metric(
    spans: list[Span],
    service: str,
    name: str,
    at: datetime,
    *,
    before: float,
    after: float,
) -> list[MetricPoint]:
    origin = min(span.start_time for span in spans)
    indexes = {
        int((span.start_time - origin).total_seconds() // 300)
        for span in spans
        if span.service_name == service and span.dependency is None
    }
    points: list[MetricPoint] = []
    for index in sorted(indexes):
        bucket_start = origin + timedelta(minutes=5 * index)
        points.append(
            MetricPoint(
                service_name=service,
                name=name,
                bucket_start=bucket_start,
                value=after if bucket_start >= at else before,
            )
        )
    return points


def _flat_cpu_metrics(spans: list[Span], service: str, value: float) -> list[MetricPoint]:
    origin = min(span.start_time for span in spans)
    indexes = {
        int((span.start_time - origin).total_seconds() // 300)
        for span in spans
        if span.service_name == service and span.dependency is None
    }
    return [
        MetricPoint(
            service_name=service,
            name="cpu_ratio",
            bucket_start=origin + timedelta(minutes=5 * index),
            value=value,
        )
        for index in sorted(indexes)
    ]


def _p95(values: list[int]) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return float(ordered[index])


def _group(spans: list[Span]) -> dict[str, list[Span]]:
    grouped: dict[str, list[Span]] = defaultdict(list)
    for span in spans:
        grouped[span.trace_id].append(span)
    return grouped
