"""Dispatch a tool call against one world slice."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime

from incident_agent.approval.actions import ActionProposal, propose_action
from incident_agent.llm.provider import ToolCall
from incident_agent.tools.config import ConfigQuery, get_configuration_changes
from incident_agent.tools.dependencies import get_dependency_health
from incident_agent.tools.deployments import DeploymentQuery, get_recent_deployments
from incident_agent.tools.knowledge import (
    get_incident_details,
    search_previous_incidents,
    search_runbooks,
)
from incident_agent.tools.logs import LogQuery, search_logs
from incident_agent.tools.metrics import MetricQuery, TimeRange, get_service_metrics
from incident_agent.tools.services import get_service_health, list_services
from incident_agent.tools.traces import TraceQuery, get_trace, search_traces
from incident_agent.world.telemetry import WorldSlice


def execute_tool(
    world: WorldSlice,
    proposals: list[ActionProposal],
    call: ToolCall,
) -> dict:
    try:
        records = _dispatch(world, proposals, call.name, call.arguments)
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "evidence_ids": [], "records": []}
    dumped = [_jsonable(record) for record in records]
    evidence_ids = [record["evidence_id"] for record in dumped if "evidence_id" in record]
    return {"ok": True, "evidence_ids": evidence_ids, "records": dumped}


def _dispatch(world: WorldSlice, proposals: list[ActionProposal], name: str, arguments: dict):
    if name == "list_services":
        return list_services(world)
    if name == "get_service_health":
        return [get_service_health(world, arguments["service_name"], _range(arguments))]
    if name == "get_service_metrics":
        return get_service_metrics(
            world,
            MetricQuery(
                service_name=arguments["service_name"],
                metric_names=tuple(arguments["metric_names"]),
                time_range=_range(arguments),
            ),
        )
    if name == "get_recent_deployments":
        return get_recent_deployments(
            world,
            DeploymentQuery(service_name=arguments["service_name"], time_range=_range(arguments)),
        )
    if name == "get_configuration_changes":
        return get_configuration_changes(
            world,
            ConfigQuery(
                service_name=arguments["service_name"],
                time_range=_range(arguments),
                change_type=arguments.get("change_type"),
            ),
        )
    if name == "search_logs":
        return search_logs(
            world,
            LogQuery(
                service_name=arguments["service_name"],
                query=arguments["query"],
                time_range=_range(arguments),
                limit=arguments.get("limit", 20),
            ),
        )
    if name == "search_traces":
        return search_traces(
            world,
            TraceQuery(
                service_name=arguments["service_name"],
                time_range=_range(arguments),
                status=arguments.get("status"),
                operation=arguments.get("operation"),
                dependency=arguments.get("dependency"),
                limit=arguments.get("limit", 20),
            ),
        )
    if name == "get_trace":
        return get_trace(world, arguments["trace_id"])
    if name == "get_dependency_health":
        return get_dependency_health(world, arguments["service_name"], _range(arguments))
    if name == "search_runbooks":
        return search_runbooks(
            world,
            arguments["query"],
            arguments.get("limit", 5),
            arguments.get("mode", "hybrid"),
        )
    if name == "search_previous_incidents":
        return search_previous_incidents(
            world,
            arguments["query"],
            arguments.get("limit", 5),
            arguments.get("mode", "hybrid"),
        )
    if name == "get_incident_details":
        return [get_incident_details(world, arguments["incident_id"])]
    if name == "propose_action":
        proposal = propose_action(
            action=arguments["action"],
            service=arguments["service"],
            at=_time(arguments["at"]),
            target_version=arguments.get("target_version"),
        )
        proposals.append(proposal)
        return [proposal]
    raise ValueError(f"unknown tool: {name}")


def _range(arguments: dict) -> TimeRange:
    raw = arguments["time_range"]
    return TimeRange(_time(raw["start"]), _time(raw["end"]))


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


def _jsonable(record) -> dict:
    if hasattr(record, "__dataclass_fields__"):
        return json.loads(json.dumps(asdict(record), default=str))
    raise TypeError("tool record must be a dataclass")
