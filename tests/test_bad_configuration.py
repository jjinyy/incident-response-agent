import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from incident_agent.world.faults import inject_bad_configuration
from incident_agent.world.telemetry import generate_healthy_checkouts


class BadConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc)
        self.changed_at = self.start + timedelta(minutes=5)
        self.healthy = generate_healthy_checkouts(10, start=self.start, spacing_seconds=60)
        self.world = inject_bad_configuration(
            self.healthy,
            service="payment-service",
            at=self.changed_at,
            key="payments.require_amount",
            old_value="true",
            new_value="false",
            change_type="feature_flag",
            error_type="InvalidAmount",
            deployed_version="v2.14.2",
            deployed_at=self.start,
        )

    def test_errors_start_at_the_config_change_not_the_deploy(self) -> None:
        self.assertEqual(len(self.world.deployments), 1)
        deploy = self.world.deployments[0]
        self.assertEqual(deploy.deployed_at, self.start)
        self.assertEqual(deploy.status, "succeeded")
        self.assertLess(deploy.deployed_at, self.changed_at)

        change = self.world.config_changes[0]
        self.assertEqual(change.key, "payments.require_amount")
        self.assertEqual(change.new_value, "false")
        self.assertEqual(change.changed_at, self.changed_at)

        payment = [
            span
            for span in self.world.spans
            if span.operation == "Authorize"
        ]
        before = [span for span in payment if span.start_time < self.changed_at]
        after = [span for span in payment if span.start_time >= self.changed_at]
        self.assertTrue(all(span.status == "ok" for span in before))
        self.assertTrue(all(span.status == "error" for span in after))
        self.assertTrue(
            all(span.attributes["deployment_version"] == "v2.14.2" for span in payment)
        )
        self.assertTrue(all(span.attributes["error_type"] == "InvalidAmount" for span in after))

    def test_paygate_stays_up_and_gateway_error_rate_follows_the_flag(self) -> None:
        paygate = [span for span in self.world.spans if span.dependency == "paygate"]
        self.assertTrue(all(span.status == "ok" for span in paygate))

        gateway = [
            point
            for point in self.world.metrics
            if point.service_name == "api-gateway" and point.name == "error_rate"
        ]
        before = next(point for point in gateway if point.bucket_start == self.start)
        after = next(point for point in gateway if point.bucket_start == self.changed_at)
        self.assertEqual(before.value, 0.0)
        self.assertEqual(after.value, 1.0)

    def test_healthy_world_is_left_unchanged(self) -> None:
        self.assertEqual(self.healthy.config_changes, [])
        self.assertTrue(all(span.status == "ok" for span in self.healthy.spans))


if __name__ == "__main__":
    unittest.main()
