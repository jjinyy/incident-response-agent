import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from incident_agent.world.faults import inject_traffic_spike
from incident_agent.world.telemetry import generate_healthy_checkouts


class TrafficSpikeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc)
        self.at = self.start + timedelta(minutes=5)
        self.world = inject_traffic_spike(
            generate_healthy_checkouts(10, start=self.start, spacing_seconds=60),
            service="api-gateway",
            at=self.at,
            extra_requests=20,
        )

    def test_requests_and_errors_rise_without_a_deploy_or_bad_dependency(self) -> None:
        self.assertEqual(self.world.deployments, [])
        self.assertEqual(self.world.config_changes, [])

        roots = [
            span
            for span in self.world.spans
            if span.service_name == "api-gateway" and span.parent_span_id is None
        ]
        before = [span for span in roots if span.start_time < self.at]
        after = [span for span in roots if span.start_time >= self.at]
        self.assertEqual(len(before), 5)
        self.assertGreater(len(after), len(before))
        self.assertTrue(all(span.status == "ok" for span in before))
        self.assertTrue(all(span.attributes.get("error_type") == "saturated" for span in after))

        for dependency in ("paygate", "postgres"):
            calls = [span for span in self.world.spans if span.dependency == dependency]
            self.assertTrue(calls)
            self.assertTrue(all(span.status == "ok" for span in calls))

    def test_cpu_and_request_rate_step_up_together(self) -> None:
        def values(name: str) -> tuple[float, float]:
            points = [
                point
                for point in self.world.metrics
                if point.service_name == "api-gateway" and point.name == name
            ]
            before = next(point.value for point in points if point.bucket_start == self.start)
            after = next(point.value for point in points if point.bucket_start == self.at)
            return before, after

        request_before, request_after = values("request_rate")
        cpu_before, cpu_after = values("cpu_ratio")
        self.assertLess(request_before, request_after)
        self.assertEqual((cpu_before, cpu_after), (0.3, 0.95))


if __name__ == "__main__":
    unittest.main()
