"""Read recent deployments from a world slice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from incident_agent.tools.metrics import TimeRange
from incident_agent.world.telemetry import WorldSlice


@dataclass(frozen=True)
class DeploymentQuery:
    service_name: str
    time_range: TimeRange


@dataclass(frozen=True)
class DeploymentRecord:
    evidence_id: str
    service_name: str
    version: str
    deployed_at: datetime
    status: str


def get_recent_deployments(world: WorldSlice, query: DeploymentQuery) -> list[DeploymentRecord]:
    """Return deploys inside the half-open range [start, end)."""
    records = [
        DeploymentRecord(
            evidence_id=_evidence_id(item.service_name, item.version, item.deployed_at),
            service_name=item.service_name,
            version=item.version,
            deployed_at=item.deployed_at,
            status=item.status,
        )
        for item in world.deployments
        if item.service_name == query.service_name
        and query.time_range.start <= item.deployed_at < query.time_range.end
    ]
    return sorted(records, key=lambda record: (record.deployed_at, record.version))


def _evidence_id(service: str, version: str, deployed_at: datetime) -> str:
    return f"deployment:{service}:{version}:{deployed_at.isoformat()}"
