"""Save and load one synthetic world in a SQLite file."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from incident_agent.world.telemetry import (
    ConfigChange,
    Deployment,
    LogEvent,
    MetricPoint,
    Runbook,
    Span,
    WorldSlice,
    HistoricalIncident,
)


def save_world(path: str | Path, world: WorldSlice) -> None:
    destination = Path(path)
    if destination.exists():
        destination.unlink()
    connection = sqlite3.connect(destination)
    try:
        connection.executescript(_SCHEMA)
        _insert_spans(connection, world.spans)
        _insert_deployments(connection, world.deployments)
        _insert_config_changes(connection, world.config_changes)
        _insert_logs(connection, world.logs)
        _insert_metrics(connection, world.metrics)
        _insert_runbooks(connection, world.runbooks)
        _insert_incidents(connection, world.incidents)
        connection.commit()
    finally:
        connection.close()


def load_world(path: str | Path) -> WorldSlice:
    connection = sqlite3.connect(path)
    try:
        connection.row_factory = sqlite3.Row
        return WorldSlice(
            spans=[_span(row) for row in connection.execute("SELECT * FROM spans ORDER BY id")],
            deployments=[
                _deployment(row)
                for row in connection.execute("SELECT * FROM deployments ORDER BY id")
            ],
            config_changes=[
                _config_change(row)
                for row in connection.execute("SELECT * FROM config_changes ORDER BY id")
            ],
            logs=[_log(row) for row in connection.execute("SELECT * FROM logs ORDER BY id")],
            metrics=[
                _metric(row) for row in connection.execute("SELECT * FROM metrics ORDER BY id")
            ],
            runbooks=[
                _runbook(row) for row in connection.execute("SELECT * FROM runbooks ORDER BY id")
            ],
            incidents=[
                _incident(row) for row in connection.execute("SELECT * FROM incidents ORDER BY id")
            ],
        )
    finally:
        connection.close()


_SCHEMA = """
CREATE TABLE spans (
    id INTEGER PRIMARY KEY,
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    parent_span_id TEXT,
    request_id TEXT NOT NULL,
    service_name TEXT NOT NULL,
    operation TEXT NOT NULL,
    start_time TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    status TEXT NOT NULL,
    dependency TEXT,
    attributes TEXT NOT NULL
);
CREATE TABLE deployments (
    id INTEGER PRIMARY KEY,
    service_name TEXT NOT NULL,
    version TEXT NOT NULL,
    deployed_at TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE config_changes (
    id INTEGER PRIMARY KEY,
    service_name TEXT NOT NULL,
    key TEXT NOT NULL,
    old_value TEXT NOT NULL,
    new_value TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    change_type TEXT NOT NULL
);
CREATE TABLE logs (
    id INTEGER PRIMARY KEY,
    service_name TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    span_id TEXT NOT NULL
);
CREATE TABLE metrics (
    id INTEGER PRIMARY KEY,
    service_name TEXT NOT NULL,
    name TEXT NOT NULL,
    bucket_start TEXT NOT NULL,
    value REAL NOT NULL,
    dependency TEXT
);
CREATE TABLE runbooks (
    id INTEGER PRIMARY KEY,
    runbook_id TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE TABLE incidents (
    id INTEGER PRIMARY KEY,
    incident_id TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    root_cause_label TEXT NOT NULL
);
"""


def _insert_spans(connection: sqlite3.Connection, spans: list[Span]) -> None:
    connection.executemany(
        """
        INSERT INTO spans (
            trace_id, span_id, parent_span_id, request_id, service_name, operation,
            start_time, duration_ms, status, dependency, attributes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                span.trace_id,
                span.span_id,
                span.parent_span_id,
                span.request_id,
                span.service_name,
                span.operation,
                span.start_time.isoformat(),
                span.duration_ms,
                span.status,
                span.dependency,
                json.dumps(span.attributes, sort_keys=True),
            )
            for span in spans
        ],
    )


def _insert_deployments(connection: sqlite3.Connection, deployments: list[Deployment]) -> None:
    connection.executemany(
        "INSERT INTO deployments (service_name, version, deployed_at, status) VALUES (?, ?, ?, ?)",
        [
            (item.service_name, item.version, item.deployed_at.isoformat(), item.status)
            for item in deployments
        ],
    )


def _insert_config_changes(connection: sqlite3.Connection, changes: list[ConfigChange]) -> None:
    connection.executemany(
        """
        INSERT INTO config_changes (
            service_name, key, old_value, new_value, changed_at, change_type
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                item.service_name,
                item.key,
                item.old_value,
                item.new_value,
                item.changed_at.isoformat(),
                item.change_type,
            )
            for item in changes
        ],
    )


def _insert_logs(connection: sqlite3.Connection, logs: list[LogEvent]) -> None:
    connection.executemany(
        """
        INSERT INTO logs (
            service_name, timestamp, level, message, trace_id, request_id, span_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                item.service_name,
                item.timestamp.isoformat(),
                item.level,
                item.message,
                item.trace_id,
                item.request_id,
                item.span_id,
            )
            for item in logs
        ],
    )


def _insert_metrics(connection: sqlite3.Connection, metrics: list[MetricPoint]) -> None:
    connection.executemany(
        """
        INSERT INTO metrics (service_name, name, bucket_start, value, dependency)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (item.service_name, item.name, item.bucket_start.isoformat(), item.value, item.dependency)
            for item in metrics
        ],
    )


def _span(row: sqlite3.Row) -> Span:
    return Span(
        trace_id=row["trace_id"],
        span_id=row["span_id"],
        parent_span_id=row["parent_span_id"],
        request_id=row["request_id"],
        service_name=row["service_name"],
        operation=row["operation"],
        start_time=_time(row["start_time"]),
        duration_ms=row["duration_ms"],
        status=row["status"],
        dependency=row["dependency"],
        attributes=json.loads(row["attributes"]),
    )


def _deployment(row: sqlite3.Row) -> Deployment:
    return Deployment(
        service_name=row["service_name"],
        version=row["version"],
        deployed_at=_time(row["deployed_at"]),
        status=row["status"],
    )


def _config_change(row: sqlite3.Row) -> ConfigChange:
    return ConfigChange(
        service_name=row["service_name"],
        key=row["key"],
        old_value=row["old_value"],
        new_value=row["new_value"],
        changed_at=_time(row["changed_at"]),
        change_type=row["change_type"],
    )


def _log(row: sqlite3.Row) -> LogEvent:
    return LogEvent(
        service_name=row["service_name"],
        timestamp=_time(row["timestamp"]),
        level=row["level"],
        message=row["message"],
        trace_id=row["trace_id"],
        request_id=row["request_id"],
        span_id=row["span_id"],
    )


def _metric(row: sqlite3.Row) -> MetricPoint:
    return MetricPoint(
        service_name=row["service_name"],
        name=row["name"],
        bucket_start=_time(row["bucket_start"]),
        value=row["value"],
        dependency=row["dependency"],
    )


def _insert_runbooks(connection: sqlite3.Connection, runbooks: list[Runbook]) -> None:
    connection.executemany(
        "INSERT INTO runbooks (runbook_id, title, body) VALUES (?, ?, ?)",
        [(item.runbook_id, item.title, item.body) for item in runbooks],
    )


def _insert_incidents(
    connection: sqlite3.Connection, incidents: list[HistoricalIncident]
) -> None:
    connection.executemany(
        """
        INSERT INTO incidents (incident_id, title, summary, root_cause_label)
        VALUES (?, ?, ?, ?)
        """,
        [(item.incident_id, item.title, item.summary, item.root_cause_label) for item in incidents],
    )


def _runbook(row: sqlite3.Row) -> Runbook:
    return Runbook(runbook_id=row["runbook_id"], title=row["title"], body=row["body"])


def _incident(row: sqlite3.Row) -> HistoricalIncident:
    return HistoricalIncident(
        incident_id=row["incident_id"],
        title=row["title"],
        summary=row["summary"],
        root_cause_label=row["root_cause_label"],
    )


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"stored timestamp is missing a timezone: {value}")
    return parsed
