"""One-line tool list for the baseline investigator."""

from __future__ import annotations

TIME_RANGE = {
    "type": "object",
    "properties": {
        "start": {"type": "string"},
        "end": {"type": "string"},
    },
    "required": ["start", "end"],
}


def _tool(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }


BASELINE_PROMPT = """You investigate one production incident by calling tools.
Use the returned evidence ids for every factual claim.
propose_action only records a high-risk action. It does not change the system.
Finish by calling submit_incident_report.
If the evidence is not enough, set status to INSUFFICIENT_EVIDENCE and root_cause to null."""

TOOLS = [
    _tool("list_services", "List services and the dependencies seen on their spans.", {}),
    _tool(
        "get_service_health",
        "Summarize server-span error rate and latency for one service.",
        {"service_name": {"type": "string"}, "time_range": TIME_RANGE},
        ["service_name", "time_range"],
    ),
    _tool(
        "get_service_metrics",
        "Return metric buckets for one service in a time range.",
        {
            "service_name": {"type": "string"},
            "metric_names": {"type": "array", "items": {"type": "string"}},
            "time_range": TIME_RANGE,
        },
        ["service_name", "metric_names", "time_range"],
    ),
    _tool(
        "get_recent_deployments",
        "Return deploys for one service in a time range.",
        {"service_name": {"type": "string"}, "time_range": TIME_RANGE},
        ["service_name", "time_range"],
    ),
    _tool(
        "get_configuration_changes",
        "Return env or feature-flag changes for one service.",
        {
            "service_name": {"type": "string"},
            "time_range": TIME_RANGE,
            "change_type": {"type": "string"},
        },
        ["service_name", "time_range"],
    ),
    _tool(
        "search_logs",
        "Find logs whose message contains a query.",
        {
            "service_name": {"type": "string"},
            "query": {"type": "string"},
            "time_range": TIME_RANGE,
            "limit": {"type": "integer"},
        },
        ["service_name", "query", "time_range"],
    ),
    _tool(
        "search_traces",
        "Find traces with a matching span.",
        {
            "service_name": {"type": "string"},
            "time_range": TIME_RANGE,
            "status": {"type": "string"},
            "operation": {"type": "string"},
            "dependency": {"type": "string"},
        },
        ["service_name", "time_range"],
    ),
    _tool(
        "get_trace",
        "Return the span tree for one trace.",
        {"trace_id": {"type": "string"}},
        ["trace_id"],
    ),
    _tool(
        "get_dependency_health",
        "Summarize client-span errors and latency by dependency.",
        {"service_name": {"type": "string"}, "time_range": TIME_RANGE},
        ["service_name", "time_range"],
    ),
    _tool(
        "search_runbooks",
        "Search runbooks with keyword overlap and character-trigram vectors.",
        {"query": {"type": "string"}},
        ["query"],
    ),
    _tool(
        "search_previous_incidents",
        "Search past incidents with keyword overlap and character-trigram vectors.",
        {"query": {"type": "string"}},
        ["query"],
    ),
    _tool(
        "get_incident_details",
        "Fetch one past incident by id.",
        {"incident_id": {"type": "string"}},
        ["incident_id"],
    ),
    _tool(
        "propose_action",
        "Record a high-risk rollback or restart for later approval.",
        {
            "action": {"type": "string"},
            "service": {"type": "string"},
            "at": {"type": "string"},
            "target_version": {"type": "string"},
        },
        ["action", "service", "at"],
    ),
    _tool(
        "submit_incident_report",
        "Submit the final report. Cite only evidence ids returned by tools.",
        {
            "incident_summary": {"type": "string"},
            "severity": {"type": "string"},
            "status": {"type": "string"},
            "affected_services": {"type": "array", "items": {"type": "string"}},
            "observations": {"type": "array"},
            "root_cause": {"type": "object"},
            "proposed_action_ids": {"type": "array", "items": {"type": "string"}},
            "missing_information": {"type": "array", "items": {"type": "string"}},
        },
        ["incident_summary", "severity", "status", "affected_services", "observations"],
    ),
]
