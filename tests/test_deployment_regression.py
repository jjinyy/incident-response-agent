import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from incident_agent.world.faults import inject_deployment_regression
from incident_agent.world.telemetry import generate_healthy_checkouts


class DeploymentRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc)
        self.deployed_at = self.start + timedelta(minutes=5)
        healthy = generate_healthy_checkouts(10, start=self.start, spacing_seconds=60)
        self.world = inject_deployment_regression(
            healthy,
            service="payment-service",
            version="v2.14.3",
            at=self.deployed_at,
            error_rate=1.0,
            error_type="NullAmount",
            seed=1,
        )

    def test_deploy_is_recorded_and_only_later_payment_spans_fail(self) -> None:
        self.assertEqual(len(self.world.deployments), 1)
        deploy = self.world.deployments[0]
        self.assertEqual(deploy.service_name, "payment-service")
        self.assertEqual(deploy.version, "v2.14.3")
        self.assertEqual(deploy.deployed_at, self.deployed_at)

        payment = [
            span
            for span in self.world.spans
            if span.service_name == "payment-service" and span.operation == "Authorize"
        ]
        before = [span for span in payment if span.start_time < self.deployed_at]
        after = [span for span in payment if span.start_time >= self.deployed_at]
        self.assertTrue(all(span.status == "ok" for span in before))
        self.assertTrue(
            all(span.attributes["deployment_version"] == "v2.14.2" for span in before)
        )
        self.assertTrue(all(span.status == "error" for span in after))
        self.assertTrue(
            all(span.attributes["deployment_version"] == "v2.14.3" for span in after)
        )
        self.assertTrue(all(span.attributes["error_type"] == "NullAmount" for span in after))

    def test_external_payment_call_stays_successful(self) -> None:
        paygate = [span for span in self.world.spans if span.dependency == "paygate"]
        after = [span for span in paygate if span.start_time >= self.deployed_at]
        self.assertTrue(after)
        self.assertTrue(all(span.status == "ok" for span in after))

    def test_gateway_error_rate_rises_in_the_bucket_after_deploy(self) -> None:
        gateway = [
            point
            for point in self.world.metrics
            if point.service_name == "api-gateway" and point.name == "error_rate"
        ]
        before = next(point for point in gateway if point.bucket_start == self.start)
        after = next(
            point for point in gateway if point.bucket_start == self.deployed_at
        )
        self.assertEqual(before.value, 0.0)
        self.assertEqual(after.value, 1.0)

    def test_error_logs_point_at_real_spans(self) -> None:
        span_ids = {span.span_id for span in self.world.spans if span.status == "error"}
        self.assertTrue(self.world.logs)
        for log in self.world.logs:
            self.assertIn(log.span_id, span_ids)
            self.assertEqual(log.trace_id.split("-")[0], "trace")

    def test_same_seed_selects_the_same_failures(self) -> None:
        healthy = generate_healthy_checkouts(20, start=self.start, spacing_seconds=30)
        kwargs = dict(
            service="payment-service",
            version="v2.14.3",
            at=self.deployed_at,
            error_rate=0.5,
            error_type="NullAmount",
            seed=7,
        )
        first = inject_deployment_regression(healthy, **kwargs)
        second = inject_deployment_regression(healthy, **kwargs)
        failed = lambda world: [
            span.span_id
            for span in world.spans
            if span.attributes.get("error_type") == "NullAmount"
        ]
        self.assertEqual(failed(first), failed(second))
        self.assertGreater(len(failed(first)), 0)
        self.assertLess(len(failed(first)), 20)


if __name__ == "__main__":
    unittest.main()
