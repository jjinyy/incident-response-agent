"""Propose actions and run them only after approval."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from incident_agent.world.replay import Remediation, apply_remediation
from incident_agent.world.telemetry import WorldSlice

HIGH_RISK_ACTIONS = ("rollback_deployment", "restart_service")


@dataclass(frozen=True)
class ActionProposal:
    action_id: str
    action: str
    service: str
    at: datetime
    target_version: str | None
    risk: str
    status: str


def propose_action(
    *,
    action: str,
    service: str,
    at: datetime,
    target_version: str | None = None,
) -> ActionProposal:
    if action not in HIGH_RISK_ACTIONS:
        raise ValueError(f"unsupported action: {action}")
    if at.tzinfo is None:
        raise ValueError("at must be timezone-aware")
    if action == "rollback_deployment" and not target_version:
        raise ValueError("rollback_deployment requires target_version")
    return ActionProposal(
        action_id=f"{action}:{service}:{at.isoformat()}",
        action=action,
        service=service,
        at=at,
        target_version=target_version,
        risk="high",
        status="PENDING_APPROVAL",
    )


def approve_action(world: WorldSlice, proposal: ActionProposal) -> tuple[WorldSlice, ActionProposal]:
    if proposal.status != "PENDING_APPROVAL":
        raise ValueError("only a pending action can be approved")
    updated = apply_remediation(
        world,
        Remediation(
            action=proposal.action,
            service=proposal.service,
            at=proposal.at,
            target_version=proposal.target_version,
        ),
    )
    executed = ActionProposal(
        action_id=proposal.action_id,
        action=proposal.action,
        service=proposal.service,
        at=proposal.at,
        target_version=proposal.target_version,
        risk=proposal.risk,
        status="EXECUTED",
    )
    return updated, executed


def reject_action(proposal: ActionProposal) -> ActionProposal:
    if proposal.status != "PENDING_APPROVAL":
        raise ValueError("only a pending action can be rejected")
    return ActionProposal(
        action_id=proposal.action_id,
        action=proposal.action,
        service=proposal.service,
        at=proposal.at,
        target_version=proposal.target_version,
        risk=proposal.risk,
        status="REJECTED",
    )
