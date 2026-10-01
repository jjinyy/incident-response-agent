"""Approve one acceptable proposal outside the agent loop and replay it.

The agent never executes the action. Recovery is omitted when the scenario
has no acceptable action.
"""

from __future__ import annotations

from incident_agent.agent.orchestrator import Investigation
from incident_agent.api.scenarios import SCENARIO_FAULT_AT
from incident_agent.approval.actions import approve_action
from incident_agent.world.telemetry import BASE_VERSIONS, WorldSlice

HARNESS = "eval_harness"


def verify_recovery(scenario: dict, world: WorldSlice, result: Investigation) -> dict:
    if not scenario["acceptable_actions"]:
        return {"recovery_verification": None, "recovery_approved_by": None}
    chosen = next(
        (item for item in result.proposals if item.action in scenario["acceptable_actions"]),
        None,
    )
    if chosen is None or chosen.service != scenario["service"]:
        return {"recovery_verification": 0.0, "recovery_approved_by": None}
    try:
        updated, executed = approve_action(world, chosen)
    except ValueError:
        return {"recovery_verification": 0.0, "recovery_approved_by": None}
    if executed.status != "EXECUTED":
        return {"recovery_verification": 0.0, "recovery_approved_by": None}
    recovered = 1.0 if _restored(updated, scenario["service"]) else 0.0
    return {"recovery_verification": recovered, "recovery_approved_by": HARNESS}


def _restored(world: WorldSlice, service: str) -> bool:
    expected = BASE_VERSIONS[service]
    checked = 0
    for span in world.spans:
        if span.service_name != service or span.dependency is not None:
            continue
        if span.start_time < SCENARIO_FAULT_AT:
            continue
        checked += 1
        if span.status != "ok":
            return False
        if span.attributes.get("deployment_version") != expected:
            return False
    return checked > 0
