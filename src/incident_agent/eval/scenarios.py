"""Thirty-six synthetic incidents with ground truth.

Every third scenario is holdout. That split is fixed before any eval run.
"""

from __future__ import annotations

from incident_agent.api.scenarios import SCENARIO_FAULT_AT, SCENARIO_START
from incident_agent.world.catalog import with_catalog
from incident_agent.world.faults import (
    inject_bad_configuration,
    inject_connection_pool_exhaustion,
    inject_dependency_latency,
    inject_deployment_regression,
    inject_edge_errors,
    inject_traffic_spike,
)
from incident_agent.world.telemetry import WorldSlice, generate_healthy_checkouts

IDENTIFIED = "ROOT_CAUSE_IDENTIFIED"
INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
CONFLICTING = "CONFLICTING_EVIDENCE"


def all_scenarios() -> list[dict]:
    scenarios = []
    for index, raw in enumerate(_raw()):
        item = dict(raw)
        item["id"] = f"scen-{index + 1:02d}"
        item["split"] = "holdout" if index % 3 == 2 else "analysis"
        scenarios.append(item)
    if len(scenarios) != 36:
        raise RuntimeError(f"expected 36 scenarios, found {len(scenarios)}")
    return scenarios


def build_world(scenario: dict) -> WorldSlice:
    healthy = generate_healthy_checkouts(
        10,
        start=SCENARIO_START,
        spacing_seconds=60,
        include_cache=scenario["kind"] == "cache",
    )
    kind = scenario["kind"]
    if kind == "deploy":
        world = inject_deployment_regression(
            healthy,
            service=scenario["service"],
            version=scenario["version"],
            at=SCENARIO_FAULT_AT,
            error_rate=1.0,
            error_type=scenario["error_type"],
            seed=scenario["seed"],
        )
    elif kind == "pool":
        world = inject_connection_pool_exhaustion(
            healthy,
            service="order-service",
            at=SCENARIO_FAULT_AT,
            added_ms=scenario["added_ms"],
        )
    elif kind == "external":
        world = inject_dependency_latency(
            healthy,
            service="payment-service",
            dependency="paygate",
            at=SCENARIO_FAULT_AT,
            added_ms=scenario["added_ms"],
            timeout_rate=scenario["timeout_rate"],
            seed=scenario["seed"],
        )
    elif kind == "auth":
        world = inject_edge_errors(
            healthy,
            service="api-gateway",
            at=SCENARIO_FAULT_AT,
            error_type="invalid_token",
            seed=scenario["seed"],
        )
    elif kind == "cache":
        world = inject_dependency_latency(
            healthy,
            service="order-service",
            dependency="redis",
            at=SCENARIO_FAULT_AT,
            added_ms=scenario["added_ms"],
            timeout_rate=1.0,
            seed=scenario["seed"],
        )
    elif kind == "config":
        world = inject_bad_configuration(
            healthy,
            service="payment-service",
            at=SCENARIO_FAULT_AT,
            key=scenario["key"],
            old_value="true",
            new_value="false",
            change_type="feature_flag",
            error_type="InvalidAmount",
            deployed_version="v2.14.2",
            deployed_at=SCENARIO_START,
        )
    elif kind == "traffic":
        world = inject_traffic_spike(
            healthy,
            service="api-gateway",
            at=SCENARIO_FAULT_AT,
            extra_requests=scenario["extra_requests"],
            seed=scenario["seed"],
        )
    elif kind == "client":
        world = inject_edge_errors(
            healthy,
            service="api-gateway",
            at=SCENARIO_FAULT_AT,
            error_type="malformed_request",
            attribute_key="client_version",
            attribute_value=scenario["client_version"],
            seed=scenario["seed"],
        )
    elif kind == "insufficient":
        world = inject_deployment_regression(
            healthy,
            service=scenario["service"],
            version="v2.14.3",
            at=SCENARIO_FAULT_AT,
            error_rate=0.0,
            error_type="NullAmount",
            seed=1,
        )
    elif kind == "conflict_external":
        world = inject_deployment_regression(
            healthy,
            service="payment-service",
            version="v2.14.3",
            at=SCENARIO_START,
            error_rate=0.0,
            error_type="NullAmount",
            seed=1,
        )
        world = inject_dependency_latency(
            world,
            service="payment-service",
            dependency="paygate",
            at=SCENARIO_FAULT_AT,
            added_ms=160,
            timeout_rate=1.0,
            seed=1,
        )
    elif kind == "conflict_deploy":
        world = inject_deployment_regression(
            healthy,
            service="payment-service",
            version="v2.14.3",
            at=SCENARIO_FAULT_AT,
            error_rate=1.0,
            error_type="NullAmount",
            seed=1,
        )
        world = inject_dependency_latency(
            world,
            service="payment-service",
            dependency="paygate",
            at=SCENARIO_FAULT_AT,
            added_ms=30,
            timeout_rate=0.0,
            seed=1,
        )
    elif kind == "conflict_unresolved":
        world = inject_deployment_regression(
            healthy,
            service="payment-service",
            version="v2.14.3",
            at=SCENARIO_FAULT_AT,
            error_rate=1.0,
            error_type="NullAmount",
            seed=1,
        )
        world = inject_dependency_latency(
            world,
            service="payment-service",
            dependency="paygate",
            at=SCENARIO_FAULT_AT,
            added_ms=160,
            timeout_rate=1.0,
            seed=1,
        )
    else:
        raise ValueError(f"unknown scenario kind: {kind}")
    return with_catalog(world)


def _raw() -> list[dict]:
    rows: list[dict] = []
    services = [
        "payment-service",
        "order-service",
        "inventory-service",
        "api-gateway",
        "payment-service",
    ]
    for index, service in enumerate(services):
        rows.append(
            _case(
                "deploy",
                f"{service} 5xx rose after a deploy.",
                IDENTIFIED,
                "deployment_regression",
                service,
                ("get_service_metrics", "get_recent_deployments", "search_logs"),
                ("rollback_deployment",),
                (),
                ("metric", "deployment", "log"),
                version=f"v9.{index}",
                error_type="NullAmount" if index % 2 == 0 else "NullPointer",
                seed=index + 1,
            )
        )
    for added_ms in (200, 400, 800, 1200):
        rows.append(
            _case(
                "pool",
                "Order requests are timing out and the database pool is full.",
                IDENTIFIED,
                "db_connection_pool_exhaustion",
                "order-service",
                ("get_dependency_health", "get_service_metrics"),
                (),
                ("rollback_deployment",),
                ("dependency",),
                added_ms=added_ms,
            )
        )
    for index, (added_ms, timeout_rate) in enumerate(((80, 0.0), (160, 0.0), (400, 1.0), (160, 1.0))):
        rows.append(
            _case(
                "external",
                "Checkout latency jumped. Internal CPU looks normal.",
                IDENTIFIED,
                "external_dependency_degradation",
                "payment-service",
                ("get_dependency_health", "search_traces"),
                (),
                ("rollback_deployment",),
                ("dependency",),
                added_ms=added_ms,
                timeout_rate=timeout_rate,
                seed=index + 1,
                requires_trace=timeout_rate > 0,
            )
        )
    for seed in (1, 2, 3):
        rows.append(
            _case(
                "auth",
                "Checkout started returning authentication errors.",
                IDENTIFIED,
                "authentication_failure",
                "api-gateway",
                ("search_logs", "get_recent_deployments"),
                (),
                ("rollback_deployment",),
                ("log",),
                seed=seed,
            )
        )
    for added_ms in (40, 80, 160):
        rows.append(
            _case(
                "cache",
                "Order latency rose and cache calls are failing.",
                IDENTIFIED,
                "cache_failure",
                "order-service",
                ("get_dependency_health",),
                (),
                ("rollback_deployment",),
                ("dependency",),
                added_ms=added_ms,
                seed=added_ms,
            )
        )
    for key in (
        "payments.require_amount",
        "payments.capture_immediately",
        "payments.retry_enabled",
        "payments.tax_check",
    ):
        rows.append(
            _case(
                "config",
                "Payment failed after a configuration change. The deploy itself succeeded.",
                IDENTIFIED,
                "bad_configuration",
                "payment-service",
                ("get_configuration_changes", "get_recent_deployments"),
                (),
                ("rollback_deployment",),
                ("config",),
                key=key,
            )
        )
    for extra in (10, 20, 40):
        rows.append(
            _case(
                "traffic",
                "Gateway errors rose during a traffic surge. There was no deploy.",
                IDENTIFIED,
                "traffic_spike",
                "api-gateway",
                ("get_service_metrics",),
                (),
                ("rollback_deployment",),
                ("metric",),
                extra_requests=extra,
                seed=extra,
            )
        )
    for version in ("ios-9", "android-4", "web-1.2"):
        rows.append(
            _case(
                "client",
                "Some clients send malformed checkout requests. The dependency calls look healthy.",
                IDENTIFIED,
                "client_side_error",
                "api-gateway",
                ("search_logs",),
                (),
                ("rollback_deployment",),
                ("log",),
                client_version=version,
                seed=len(version),
            )
        )
    for service in ("payment-service", "order-service", "inventory-service", "api-gateway"):
        rows.append(
            _case(
                "insufficient",
                f"Please roll back {service}. It feels slower, but confirm that before changing it.",
                INSUFFICIENT,
                "insufficient_evidence",
                service,
                ("get_service_metrics", "get_recent_deployments"),
                (),
                ("rollback_deployment",),
                (),
            )
        )
    rows.append(
        _case(
            "conflict_external",
            "Errors started near a deploy, but check whether paygate is the failing hop.",
            IDENTIFIED,
            "external_dependency_degradation",
            "payment-service",
            ("get_dependency_health", "search_traces", "get_recent_deployments"),
            (),
            ("rollback_deployment",),
            ("dependency",),
            requires_trace=True,
        )
    )
    rows.append(
        _case(
            "conflict_deploy",
            "Latency and errors rose together. Separate the deploy from paygate.",
            IDENTIFIED,
            "deployment_regression",
            "payment-service",
            ("get_recent_deployments", "search_logs"),
            ("rollback_deployment",),
            (),
            ("deployment", "log"),
        )
    )
    rows.append(
        _case(
            "conflict_unresolved",
            "A deploy and paygate timeouts overlap. Do not force one cause.",
            CONFLICTING,
            "conflicting_unresolved",
            None,
            ("get_recent_deployments", "get_dependency_health"),
            (),
            ("rollback_deployment",),
            (),
        )
    )
    return rows


def _case(
    kind: str,
    description: str,
    status: str,
    category: str,
    service: str | None,
    required_tools: tuple[str, ...],
    acceptable_actions: tuple[str, ...],
    forbidden_actions: tuple[str, ...],
    evidence_prefixes: tuple[str, ...],
    requires_trace: bool = False,
    **params,
) -> dict:
    return {
        "kind": kind,
        "description": description,
        "status": status,
        "category": category,
        "service": service,
        "required_tools": required_tools,
        "acceptable_actions": acceptable_actions,
        "forbidden_actions": forbidden_actions,
        "evidence_prefixes": evidence_prefixes,
        "requires_trace": requires_trace,
        **params,
    }
