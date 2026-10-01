import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from incident_agent.world.telemetry import (
    check_trace_consistency,
    generate_healthy_checkouts,
)


class HealthyCheckoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc)
        self.world = generate_healthy_checkouts(3, start=self.start)

    def test_each_request_has_the_checkout_tree(self) -> None:
        traces = self.world.by_trace()
        self.assertEqual(set(traces), {"trace-0000", "trace-0001", "trace-0002"})
        for spans in traces.values():
            check_trace_consistency(spans)
            ops = {(span.service_name, span.operation, span.dependency) for span in spans}
            self.assertIn(("api-gateway", "POST /checkout", None), ops)
            self.assertIn(("order-service", "CreateOrder", None), ops)
            self.assertIn(("order-service", "SELECT orders", "postgres"), ops)
            self.assertIn(("payment-service", "Authorize", None), ops)
            self.assertIn(("payment-service", "POST /charges", "paygate"), ops)
            self.assertIn(("inventory-service", "ReserveStock", None), ops)

    def test_edge_id_is_not_the_trace_id(self) -> None:
        first = self.world.by_trace()["trace-0000"][0]
        self.assertEqual(first.request_id, "req-0000")
        self.assertNotEqual(first.trace_id, first.request_id)

    def test_healthy_spans_are_ok_and_versions_are_baseline(self) -> None:
        for span in self.world.spans:
            self.assertEqual(span.status, "ok")
            self.assertIn("deployment_version", span.attributes)

    def test_requests_are_spaced(self) -> None:
        roots = [
            next(span for span in spans if span.parent_span_id is None)
            for spans in self.world.by_trace().values()
        ]
        roots.sort(key=lambda span: span.start_time)
        gap = roots[1].start_time - roots[0].start_time
        self.assertEqual(gap.total_seconds(), 1)

    def test_broken_parent_link_is_rejected(self) -> None:
        spans = list(self.world.by_trace()["trace-0000"])
        broken = spans[1]
        spans[1] = type(broken)(
            trace_id=broken.trace_id,
            span_id=broken.span_id,
            parent_span_id="missing-parent",
            request_id=broken.request_id,
            service_name=broken.service_name,
            operation=broken.operation,
            start_time=broken.start_time,
            duration_ms=broken.duration_ms,
            status=broken.status,
            dependency=broken.dependency,
            attributes=dict(broken.attributes),
        )
        with self.assertRaises(ValueError):
            check_trace_consistency(spans)


if __name__ == "__main__":
    unittest.main()
