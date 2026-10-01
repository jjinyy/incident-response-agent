"""Apply a remediation to a world slice.

A matching rollback repairs later requests. A restart leaves the fault in place.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from incident_agent.world.faults import (
    _copy_spans,
    _error_rate_metrics,
    _group,
    _logs_for_errors,
)
from incident_agent.world.telemetry import Deployment, Span, WorldSlice, check_trace_consistency


@dataclass(frozen=True)
class Remediation:
    action: str
    service: str
    at: datetime
    target_version: str | None = None


def apply_remediation(world: WorldSlice, action: Remediation) -> WorldSlice:
    if action.at.tzinfo is None:
        raise ValueError("at must be timezone-aware")
    spans = _copy_spans(world)
    deployments = list(world.deployments)

    if action.action == "rollback_deployment":
        if not action.target_version:
            raise ValueError("rollback_deployment requires target_version")
        repaired = _roll_back(spans, action.service, action.at, action.target_version)
        if repaired == 0:
            raise ValueError(f"no {action.service} spans to roll back at {action.at.isoformat()}")
        _clear_downstream_errors(spans)
        deployments.append(
            Deployment(
                service_name=action.service,
                version=action.target_version,
                deployed_at=action.at,
                status="rolled_back",
            )
        )
    elif action.action == "restart_service":
        pass
    else:
        raise ValueError(f"unsupported action: {action.action}")

    for trace_spans in _group(spans).values():
        check_trace_consistency(trace_spans)

    return WorldSlice(
        spans=spans,
        deployments=deployments,
        config_changes=list(world.config_changes),
        logs=_logs_for_errors(spans),
        metrics=_error_rate_metrics(spans),
        runbooks=list(world.runbooks),
        incidents=list(world.incidents),
    )


def _roll_back(spans: list[Span], service: str, at: datetime, target_version: str) -> int:
    repaired = 0
    for span in spans:
        if span.service_name != service or span.dependency is not None or span.start_time < at:
            continue
        span.status = "ok"
        span.attributes.pop("error_type", None)
        span.attributes["deployment_version"] = target_version
        repaired += 1
    return repaired


def _clear_downstream_errors(spans: list[Span]) -> None:
    children: dict[str, list[Span]] = defaultdict(list)
    for span in spans:
        if span.parent_span_id is not None:
            children[span.parent_span_id].append(span)

    changed = True
    while changed:
        changed = False
        for span in spans:
            if span.attributes.get("error_type") != "downstream_error":
                continue
            if children[span.span_id] and all(child.status == "ok" for child in children[span.span_id]):
                span.status = "ok"
                span.attributes.pop("error_type", None)
                changed = True
