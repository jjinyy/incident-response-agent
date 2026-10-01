import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from incident_agent.tools.deployments import DeploymentQuery, get_recent_deployments
from incident_agent.tools.metrics import TimeRange
from incident_agent.world.faults import inject_deployment_regression
from incident_agent.world.telemetry import generate_healthy_checkouts


class GetRecentDeploymentsTests(unittest.TestCase):
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

    def test_returns_the_deploy_inside_the_range(self) -> None:
        records = get_recent_deployments(
            self.world,
            DeploymentQuery(
                service_name="payment-service",
                time_range=TimeRange(self.start, self.deployed_at + timedelta(minutes=5)),
            ),
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].version, "v2.14.3")
        self.assertEqual(records[0].status, "succeeded")
        self.assertEqual(records[0].deployed_at, self.deployed_at)
        self.assertEqual(
            records[0].evidence_id,
            f"deployment:payment-service:v2.14.3:{self.deployed_at.isoformat()}",
        )

    def test_excludes_other_services_and_ranges_before_the_deploy(self) -> None:
        before = get_recent_deployments(
            self.world,
            DeploymentQuery(
                service_name="payment-service",
                time_range=TimeRange(self.start, self.deployed_at),
            ),
        )
        other = get_recent_deployments(
            self.world,
            DeploymentQuery(
                service_name="order-service",
                time_range=TimeRange(self.start, self.deployed_at + timedelta(minutes=5)),
            ),
        )
        self.assertEqual(before, [])
        self.assertEqual(other, [])


if __name__ == "__main__":
    unittest.main()
