import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from incident_agent.tools.logs import LogQuery, search_logs
from incident_agent.tools.metrics import TimeRange
from incident_agent.world.faults import inject_deployment_regression
from incident_agent.world.telemetry import generate_healthy_checkouts


class SearchLogsTests(unittest.TestCase):
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
        self.window = TimeRange(self.start, self.deployed_at + timedelta(minutes=5))

    def test_finds_payment_errors_after_the_deploy(self) -> None:
        records = search_logs(
            self.world,
            LogQuery(service_name="payment-service", query="nullamount", time_range=self.window),
        )
        self.assertTrue(records)
        self.assertTrue(all(record.message == "NullAmount in Authorize" for record in records))
        self.assertTrue(all(record.timestamp >= self.deployed_at for record in records))
        self.assertTrue(all(record.evidence_id == f"log:{record.span_id}" for record in records))

    def test_misses_other_services_and_respects_limit(self) -> None:
        gateway = search_logs(
            self.world,
            LogQuery(service_name="api-gateway", query="NullAmount", time_range=self.window),
        )
        limited = search_logs(
            self.world,
            LogQuery(
                service_name="payment-service",
                query="Authorize",
                time_range=self.window,
                limit=2,
            ),
        )
        self.assertEqual(gateway, [])
        self.assertEqual(len(limited), 2)
        self.assertLessEqual(limited[0].timestamp, limited[1].timestamp)


if __name__ == "__main__":
    unittest.main()
