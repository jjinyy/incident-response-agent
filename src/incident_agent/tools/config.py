"""Read configuration changes from a world slice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from incident_agent.tools.metrics import TimeRange
from incident_agent.world.telemetry import WorldSlice


@dataclass(frozen=True)
class ConfigQuery:
    service_name: str
    time_range: TimeRange
    change_type: str | None = None

    def __post_init__(self) -> None:
        if self.change_type not in (None, "env", "feature_flag"):
            raise ValueError("change_type must be env or feature_flag")


@dataclass(frozen=True)
class ConfigRecord:
    evidence_id: str
    service_name: str
    key: str
    old_value: str
    new_value: str
    changed_at: datetime
    change_type: str


def get_configuration_changes(world: WorldSlice, query: ConfigQuery) -> list[ConfigRecord]:
    """Return config changes inside the half-open range [start, end)."""
    records = [
        ConfigRecord(
            evidence_id=_evidence_id(item.service_name, item.key, item.changed_at),
            service_name=item.service_name,
            key=item.key,
            old_value=item.old_value,
            new_value=item.new_value,
            changed_at=item.changed_at,
            change_type=item.change_type,
        )
        for item in world.config_changes
        if item.service_name == query.service_name
        and query.time_range.start <= item.changed_at < query.time_range.end
        and (query.change_type is None or item.change_type == query.change_type)
    ]
    return sorted(records, key=lambda record: (record.changed_at, record.key))


def _evidence_id(service: str, key: str, changed_at: datetime) -> str:
    return f"config:{service}:{key}:{changed_at.isoformat()}"
