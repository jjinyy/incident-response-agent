import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from incident_agent.tools.metrics import MetricQuery, TimeRange, get_service_metrics
from incident_agent.world.faults import inject_deployment_regression
from incident_agent.world.telemetry import generate_healthy_checkouts


class GetServiceMetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc)
        self.deployed_at = self.start + timedelta(minutes=5)
        self.world = inject_deployment_regression(
            generate_healthy_checkouts(10, start=self.start, spacing_seconds=60),
            service="payment-service",
            version="v2.14.3",
            at=self.deployed_at,
            error_rate=1.0,
            error_type="NullAmount",
            seed=1,
        )

    def test_range_selects_the_bucket_after_the_deploy(self) -> None:
        records = get_service_metrics(
            self.world,
            MetricQuery(
                service_name="api-gateway",
                metric_names=("error_rate",),
                time_range=TimeRange(self.deployed_at, self.deployed_at + timedelta(minutes=5)),
            ),
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].value, 1.0)
        self.assertEqual(
            records[0].evidence_id,
            f"metric:api-gateway:error_rate:-:{self.deployed_at.isoformat()}",
        )

    def test_earlier_range_stays_healthy_and_other_services_are_excluded(self) -> None:
        records = get_service_metrics(
            self.world,
            MetricQuery(
                service_name="api-gateway",
                metric_names=("error_rate",),
                time_range=TimeRange(self.start, self.deployed_at),
            ),
        )
        self.assertEqual([record.value for record in records], [0.0])
        other = get_service_metrics(
            self.world,
            MetricQuery(
                service_name="notification-service",
                metric_names=("error_rate",),
                time_range=TimeRange(self.start, self.deployed_at + timedelta(minutes=5)),
            ),
        )
        self.assertEqual(other, [])


if __name__ == "__main__":
    unittest.main()
