"""Search error logs in a world slice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from incident_agent.tools.metrics import TimeRange
from incident_agent.world.telemetry import WorldSlice


@dataclass(frozen=True)
class LogQuery:
    service_name: str
    query: str
    time_range: TimeRange
    limit: int = 20

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("query must not be empty")
        if self.limit < 1:
            raise ValueError("limit must be >= 1")


@dataclass(frozen=True)
class LogRecord:
    evidence_id: str
    service_name: str
    timestamp: datetime
    level: str
    message: str
    trace_id: str
    request_id: str
    span_id: str


def search_logs(world: WorldSlice, query: LogQuery) -> list[LogRecord]:
    """Return up to `limit` logs whose message contains the query, case-insensitive."""
    needle = query.query.casefold()
    matched = [
        item
        for item in world.logs
        if item.service_name == query.service_name
        and needle in item.message.casefold()
        and query.time_range.start <= item.timestamp < query.time_range.end
    ]
    matched.sort(key=lambda item: (item.timestamp, item.span_id))
    return [
        LogRecord(
            evidence_id=f"log:{item.span_id}",
            service_name=item.service_name,
            timestamp=item.timestamp,
            level=item.level,
            message=item.message,
            trace_id=item.trace_id,
            request_id=item.request_id,
            span_id=item.span_id,
        )
        for item in matched[: query.limit]
    ]
