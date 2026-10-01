import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from incident_agent.approval.actions import approve_action, propose_action, reject_action
from incident_agent.world.faults import inject_deployment_regression
from incident_agent.world.telemetry import generate_healthy_checkouts


class ApprovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc)
        self.deployed_at = self.start + timedelta(minutes=5)
        self.rolled_at = self.start + timedelta(minutes=10)
        self.world = inject_deployment_regression(
            generate_healthy_checkouts(15, start=self.start, spacing_seconds=60),
            service="payment-service",
            version="v2.14.3",
            at=self.deployed_at,
            error_rate=1.0,
            error_type="NullAmount",
            seed=1,
        )

    def _gateway_rate(self, world, bucket: datetime) -> float:
        return next(
            point.value
            for point in world.metrics
            if point.service_name == "api-gateway"
            and point.name == "error_rate"
            and point.bucket_start == bucket
        )

    def test_rollback_waits_for_approval(self) -> None:
        proposal = propose_action(
            action="rollback_deployment",
            service="payment-service",
            at=self.rolled_at,
            target_version="v2.14.2",
        )
        self.assertEqual(proposal.status, "PENDING_APPROVAL")
        self.assertEqual(proposal.risk, "high")
        self.assertEqual(self._gateway_rate(self.world, self.rolled_at), 1.0)

        rejected = reject_action(proposal)
        self.assertEqual(rejected.status, "REJECTED")
        self.assertEqual(self._gateway_rate(self.world, self.rolled_at), 1.0)

        updated, executed = approve_action(self.world, proposal)
        self.assertEqual(executed.status, "EXECUTED")
        self.assertEqual(self._gateway_rate(updated, self.rolled_at), 0.0)
        self.assertEqual(self._gateway_rate(self.world, self.rolled_at), 1.0)

    def test_restart_approval_does_not_clear_errors(self) -> None:
        proposal = propose_action(
            action="restart_service",
            service="payment-service",
            at=self.rolled_at,
        )
        updated, executed = approve_action(self.world, proposal)
        self.assertEqual(executed.status, "EXECUTED")
        self.assertEqual(self._gateway_rate(updated, self.rolled_at), 1.0)


if __name__ == "__main__":
    unittest.main()
