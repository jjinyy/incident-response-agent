import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from incident_agent.tools.dependencies import get_dependency_health
from incident_agent.tools.metrics import TimeRange
from incident_agent.tools.services import get_service_health, list_services
from incident_agent.world.faults import inject_connection_pool_exhaustion, inject_deployment_regression
from incident_agent.world.telemetry import generate_healthy_checkouts


class ServiceToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc)
        self.at = self.start + timedelta(minutes=5)
        self.window = TimeRange(self.at, self.at + timedelta(minutes=5))
        healthy = generate_healthy_checkouts(10, start=self.start, spacing_seconds=60)
        self.regression = inject_deployment_regression(
            healthy,
            service="payment-service",
            version="v2.14.3",
            at=self.at,
            error_rate=1.0,
            error_type="NullAmount",
            seed=1,
        )
        self.pool = inject_connection_pool_exhaustion(healthy, service="order-service", at=self.at)

    def test_lists_dependencies_seen_on_spans(self) -> None:
        services = {item.service_name: item.dependencies for item in list_services(self.regression)}
        self.assertIn("paygate", services["payment-service"])
        self.assertIn("postgres", services["order-service"])
        self.assertEqual(services["api-gateway"], ())

    def test_gateway_health_shows_the_error_spike(self) -> None:
        health = get_service_health(self.regression, "api-gateway", self.window)
        self.assertEqual(health.error_rate, 1.0)
        self.assertGreater(health.request_count, 0)

    def test_dependency_health_separates_paygate_from_postgres(self) -> None:
        paygate = get_dependency_health(self.regression, "payment-service", self.window)
        self.assertEqual(paygate[0].dependency, "paygate")
        self.assertEqual(paygate[0].error_rate, 0.0)

        postgres = get_dependency_health(self.pool, "order-service", self.window)
        self.assertEqual(postgres[0].dependency, "postgres")
        self.assertEqual(postgres[0].error_rate, 1.0)
        self.assertGreater(postgres[0].latency_p95_ms, 40)


if __name__ == "__main__":
    unittest.main()
