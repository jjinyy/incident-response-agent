import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from incident_agent.tools.traces import get_trace
from incident_agent.world.faults import inject_deployment_regression
from incident_agent.world.telemetry import generate_healthy_checkouts


class GetTraceTests(unittest.TestCase):
    def setUp(self) -> None:
        start = datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc)
        self.world = inject_deployment_regression(
            generate_healthy_checkouts(6, start=start, spacing_seconds=60),
            service="payment-service",
            version="v2.14.3",
            at=start + timedelta(minutes=5),
            error_rate=1.0,
            error_type="NullAmount",
            seed=1,
        )

    def test_tree_shows_payment_error_and_healthy_paygate(self) -> None:
        spans = get_trace(self.world, "trace-0005")
        self.assertEqual(spans[0].operation, "POST /checkout")
        self.assertIsNone(spans[0].parent_span_id)
        by_operation = {span.operation: span for span in spans}
        self.assertEqual(by_operation["Authorize"].status, "error")
        self.assertEqual(by_operation["Authorize"].parent_span_id, "trace-0005-order")
        self.assertEqual(by_operation["POST /charges"].status, "ok")
        self.assertEqual(by_operation["POST /charges"].dependency, "paygate")
        self.assertEqual(by_operation["POST /charges"].parent_span_id, "trace-0005-payment")
        self.assertTrue(all(span.evidence_id == f"span:{span.span_id}" for span in spans))
        self.assertEqual(len(spans), 6)

    def test_unknown_trace_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            get_trace(self.world, "trace-missing")


if __name__ == "__main__":
    unittest.main()
