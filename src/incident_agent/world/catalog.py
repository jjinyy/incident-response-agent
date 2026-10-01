"""Small runbook and past-incident catalog stored on a world slice."""

from incident_agent.world.telemetry import HistoricalIncident, Runbook, WorldSlice

RUNBOOKS = [
    Runbook(
        runbook_id="rb-deploy-regression",
        title="Payment error rate after a deploy",
        body="If payment 5xx starts at a new version and paygate spans stay ok, roll back to the previous version.",
    ),
    Runbook(
        runbook_id="rb-paygate-latency",
        title="Checkout latency from paygate",
        body="If time is spent in the paygate client span and CPU is flat, treat it as external dependency degradation. Do not roll back.",
    ),
    Runbook(
        runbook_id="rb-pool",
        title="Postgres connection pool exhaustion",
        body="Pool usage near 1.0 with postgres timeouts and normal CPU means pool exhaustion, not a bad deploy.",
    ),
    Runbook(
        runbook_id="rb-config",
        title="Failure after a feature flag",
        body="If the version did not change and errors start at a config change, revert the flag instead of rolling back the deploy.",
    ),
]

INCIDENTS = [
    HistoricalIncident(
        incident_id="inc-pay-2024",
        title="Payment v2.8 deploy regression",
        summary="5xx started at payment deploy v2.8. Paygate was healthy. Rollback fixed it.",
        root_cause_label="deployment_regression",
    ),
    HistoricalIncident(
        incident_id="inc-paygate-2025",
        title="Paygate timeout",
        summary="Checkout latency followed paygate timeouts. Internal CPU stayed normal.",
        root_cause_label="external_dependency_degradation",
    ),
    HistoricalIncident(
        incident_id="inc-pool-2024",
        title="Order pool saturation",
        summary="Order postgres calls timed out while the pool was full and CPU was normal.",
        root_cause_label="db_connection_pool_exhaustion",
    ),
    HistoricalIncident(
        incident_id="inc-flag-2025",
        title="Amount check flag disabled",
        summary="A successful deploy was followed later by payments.require_amount=false and InvalidAmount errors.",
        root_cause_label="bad_configuration",
    ),
]


def with_catalog(world: WorldSlice) -> WorldSlice:
    return WorldSlice(
        spans=world.spans,
        deployments=list(world.deployments),
        config_changes=list(world.config_changes),
        logs=list(world.logs),
        metrics=list(world.metrics),
        runbooks=list(RUNBOOKS),
        incidents=list(INCIDENTS),
    )
