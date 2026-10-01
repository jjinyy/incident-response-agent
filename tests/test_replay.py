import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from incident_agent.world.faults import inject_deployment_regression
from incident_agent.world.replay import Remediation, apply_remediation
from incident_agent.world.telemetry import generate_healthy_checkouts


class ReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc)
        self.deployed_at = self.start + timedelta(minutes=5)
        self.rolled_at = self.start + timedelta(minutes=10)
        self.broken = inject_deployment_regression(
            generate_healthy_checkouts(15, start=self.start, spacing_seconds=60),
            service="payment-service",
            version="v2.14.3",
            at=self.deployed_at,
            error_rate=1.0,
            error_type="NullAmount",
            seed=1,
        )

    def test_rollback_repairs_only_later_requests(self) -> None:
        repaired = apply_remediation(
            self.broken,
            Remediation(
                action="rollback_deployment",
                service="payment-service",
                at=self.rolled_at,
                target_version="v2.14.2",
            ),
        )
        self.assertEqual(repaired.deployments[-1].status, "rolled_back")
        self.assertEqual(repaired.deployments[-1].version, "v2.14.2")

        def gateway_rate(bucket: datetime) -> float:
            return next(
                point.value
                for point in repaired.metrics
                if point.service_name == "api-gateway"
                and point.name == "error_rate"
                and point.bucket_start == bucket
            )

        self.assertEqual(gateway_rate(self.deployed_at), 1.0)
        self.assertEqual(gateway_rate(self.rolled_at), 0.0)
        later = [
            span
            for span in repaired.spans
            if span.operation == "Authorize" and span.start_time >= self.rolled_at
        ]
        self.assertTrue(all(span.status == "ok" for span in later))
        self.assertTrue(all(span.attributes["deployment_version"] == "v2.14.2" for span in later))
        self.assertTrue(any(span.status == "error" for span in self.broken.spans))

    def test_restart_leaves_the_fault(self) -> None:
        restarted = apply_remediation(
            self.broken,
            Remediation(action="restart_service", service="payment-service", at=self.rolled_at),
        )
        rate = next(
            point.value
            for point in restarted.metrics
            if point.service_name == "api-gateway"
            and point.name == "error_rate"
            and point.bucket_start == self.rolled_at
        )
        self.assertEqual(rate, 1.0)
        self.assertEqual(len(restarted.deployments), len(self.broken.deployments))


if __name__ == "__main__":
    unittest.main()
