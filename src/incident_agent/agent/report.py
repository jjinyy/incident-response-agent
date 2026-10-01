"""Validate the structured incident report against collected evidence."""

from __future__ import annotations

CATEGORIES = {
    "deployment_regression",
    "db_connection_pool_exhaustion",
    "external_dependency_degradation",
    "authentication_failure",
    "cache_failure",
    "bad_configuration",
    "traffic_spike",
    "client_side_error",
    "insufficient_evidence",
    "conflicting_unresolved",
}

IDENTIFIED = "ROOT_CAUSE_IDENTIFIED"
INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
CONFLICTING = "CONFLICTING_EVIDENCE"
STATUSES = {IDENTIFIED, INSUFFICIENT, CONFLICTING}


def validate_report(report: dict, evidence_ids: set[str], action_ids: set[str]) -> list[str]:
    errors: list[str] = []
    if not isinstance(report, dict):
        return ["report must be an object"]
    status = report.get("status")
    if status not in STATUSES:
        errors.append("status is missing or unknown")
    if report.get("severity") not in {"sev1", "sev2", "sev3", "sev4"}:
        errors.append("severity is missing or unknown")

    observations = report.get("observations", [])
    if not isinstance(observations, list):
        errors.append("observations must be a list")
        observations = []
    for index, observation in enumerate(observations):
        errors.extend(_check_ids(observation, evidence_ids, f"observations[{index}]"))

    root = report.get("root_cause")
    if status == IDENTIFIED:
        if not isinstance(root, dict):
            errors.append("root_cause is required")
        else:
            if root.get("category") not in CATEGORIES - {"insufficient_evidence"}:
                errors.append("root_cause.category is missing or not a finding category")
            if not root.get("service"):
                errors.append("root_cause.service is required")
            errors.extend(_check_ids(root, evidence_ids, "root_cause"))
    elif status in {INSUFFICIENT, CONFLICTING} and root is not None:
        errors.append("root_cause must be null unless a cause is identified")

    for action_id in report.get("proposed_action_ids", []):
        if action_id not in action_ids:
            errors.append(f"unknown proposed action: {action_id}")
    return errors


def _check_ids(claim: dict, evidence_ids: set[str], label: str) -> list[str]:
    if not isinstance(claim, dict):
        return [f"{label} must be an object"]
    ids = claim.get("evidence_ids")
    if not isinstance(ids, list) or not ids:
        return [f"{label} needs evidence_ids"]
    return [f"{label} cites unknown evidence {item}" for item in ids if item not in evidence_ids]
