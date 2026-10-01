import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from incident_agent.tools.metrics import TimeRange
from incident_agent.tools.traces import TraceQuery, search_traces
from incident_agent.world.faults import inject_deployment_regression
from incident_agent.world.telemetry import generate_healthy_checkouts


class SearchTracesTests(unittest.TestCase):
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

    def test_error_authorize_spans_point_at_payment_not_paygate(self) -> None:
        records = search_traces(
            self.world,
            TraceQuery(
                service_name="payment-service",
                time_range=self.window,
                status="error",
                operation="Authorize",
            ),
        )
        self.assertTrue(records)
        self.assertTrue(all(record.matched_operation == "Authorize" for record in records))
        self.assertTrue(all(record.matched_dependency is None for record in records))
        self.assertTrue(all(record.root_operation == "POST /checkout" for record in records))
        self.assertTrue(all(record.root_status == "error" for record in records))
        self.assertTrue(all(record.start_time >= self.deployed_at for record in records))
        self.assertTrue(all(record.evidence_id == f"trace:{record.trace_id}" for record in records))

    def test_paygate_timeouts_are_absent_and_limit_applies(self) -> None:
        paygate = search_traces(
            self.world,
            TraceQuery(
                service_name="payment-service",
                time_range=self.window,
                status="timeout",
                dependency="paygate",
            ),
        )
        limited = search_traces(
            self.world,
            TraceQuery(
                service_name="payment-service",
                time_range=self.window,
                status="error",
                operation="Authorize",
                limit=2,
            ),
        )
        self.assertEqual(paygate, [])
        self.assertEqual(len(limited), 2)


if __name__ == "__main__":
    unittest.main()
