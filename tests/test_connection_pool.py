import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from incident_agent.world.faults import inject_connection_pool_exhaustion
from incident_agent.world.telemetry import generate_healthy_checkouts


class ConnectionPoolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc)
        self.at = self.start + timedelta(minutes=5)
        self.world = inject_connection_pool_exhaustion(
            generate_healthy_checkouts(10, start=self.start, spacing_seconds=60),
            service="order-service",
            at=self.at,
        )

    def test_later_postgres_calls_time_out_and_paygate_stays_healthy(self) -> None:
        self.assertEqual(self.world.deployments, [])
        self.assertEqual(self.world.config_changes, [])

        postgres = [span for span in self.world.spans if span.dependency == "postgres"]
        before = [span for span in postgres if span.start_time < self.at]
        after = [span for span in postgres if span.start_time >= self.at]
        self.assertTrue(all(span.status == "ok" and span.duration_ms == 8 for span in before))
        self.assertTrue(all(span.status == "timeout" for span in after))
        self.assertTrue(
            all(span.attributes["error_type"] == "connection_pool_timeout" for span in after)
        )

        paygate = [span for span in self.world.spans if span.dependency == "paygate"]
        self.assertTrue(all(span.status == "ok" and span.duration_ms == 40 for span in paygate))

    def test_pool_saturates_while_cpu_stays_flat(self) -> None:
        pool = [
            point
            for point in self.world.metrics
            if point.service_name == "order-service" and point.name == "db_pool_usage"
        ]
        self.assertEqual(
            [point.value for point in pool if point.bucket_start == self.start], [0.4]
        )
        self.assertEqual(
            [point.value for point in pool if point.bucket_start == self.at], [1.0]
        )
        cpu = [
            point.value
            for point in self.world.metrics
            if point.service_name == "order-service" and point.name == "cpu_ratio"
        ]
        self.assertEqual(cpu, [0.3, 0.3])


if __name__ == "__main__":
    unittest.main()
