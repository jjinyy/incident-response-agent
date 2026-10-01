"""Named worlds the API can investigate."""

from datetime import datetime, timedelta, timezone

from incident_agent.world.catalog import with_catalog
from incident_agent.world.faults import inject_dependency_latency, inject_deployment_regression
from incident_agent.world.telemetry import WorldSlice, generate_healthy_checkouts

SCENARIO_START = datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc)
SCENARIO_FAULT_AT = SCENARIO_START + timedelta(minutes=5)

SCENARIOS = ("payment_deploy_regression", "paygate_latency")


def build_scenario(name: str) -> WorldSlice:
    healthy = generate_healthy_checkouts(10, start=SCENARIO_START, spacing_seconds=60)
    if name == "payment_deploy_regression":
        world = inject_deployment_regression(
            healthy,
            service="payment-service",
            version="v2.14.3",
            at=SCENARIO_FAULT_AT,
            error_rate=1.0,
            error_type="NullAmount",
            seed=1,
        )
    elif name == "paygate_latency":
        world = inject_dependency_latency(
            healthy,
            service="payment-service",
            dependency="paygate",
            at=SCENARIO_FAULT_AT,
            added_ms=160,
        )
    else:
        raise ValueError(f"unknown scenario: {name}")
    return with_catalog(world)
