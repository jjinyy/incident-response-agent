import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from incident_agent.world.faults import inject_dependency_latency
from incident_agent.world.telemetry import generate_healthy_checkouts


class DependencyLatencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc)
        self.at = self.start + timedelta(minutes=5)
        self.healthy = generate_healthy_checkouts(10, start=self.start, spacing_seconds=60)
        self.healthy_durations = [span.duration_ms for span in self.healthy.spans]
        self.world = inject_dependency_latency(
            self.healthy,
            service="payment-service",
            dependency="paygate",
            at=self.at,
            added_ms=160,
        )

    def test_only_later_paygate_calls_grow_and_callers_keep_their_own_work(self) -> None:
        self.assertEqual(
            self.healthy_durations, [span.duration_ms for span in self.healthy.spans]
        )
        self.assertEqual(self.world.deployments, [])

        healthy_traces = self.healthy.by_trace()
        for trace_id, spans in self.world.by_trace().items():
            paygate = next(span for span in spans if span.dependency == "paygate")
            payment = next(span for span in spans if span.operation == "Authorize")
            before = healthy_traces[trace_id]
            before_paygate = next(span for span in before if span.dependency == "paygate")
            before_payment = next(span for span in before if span.operation == "Authorize")
            own_work = payment.duration_ms - paygate.duration_ms
            self.assertEqual(
                own_work, before_payment.duration_ms - before_paygate.duration_ms
            )
            if paygate.start_time < self.at:
                self.assertEqual(paygate.duration_ms, 40)
            else:
                self.assertEqual(paygate.duration_ms, 200)
                self.assertEqual(paygate.status, "ok")

    def test_gateway_latency_rises_while_cpu_and_error_rate_stay_flat(self) -> None:
        def point(name: str, bucket: datetime, dependency: str | None = None) -> float:
            matches = [
                item
                for item in self.world.metrics
                if item.service_name == "api-gateway"
                and item.name == name
                and item.bucket_start == bucket
                and item.dependency == dependency
            ]
            self.assertEqual(len(matches), 1)
            return matches[0].value

        self.assertLess(point("latency_p95_ms", self.start), point("latency_p95_ms", self.at))
        self.assertEqual(point("error_rate", self.at), 0.0)

        cpu = [
            item.value
            for item in self.world.metrics
            if item.service_name == "payment-service" and item.name == "cpu_ratio"
        ]
        self.assertEqual(cpu, [0.3, 0.3])

        paygate = [
            item
            for item in self.world.metrics
            if item.name == "dependency_latency_p95_ms" and item.dependency == "paygate"
        ]
        before = next(item for item in paygate if item.bucket_start == self.start)
        after = next(item for item in paygate if item.bucket_start == self.at)
        self.assertEqual(before.value, 40.0)
        self.assertEqual(after.value, 200.0)

    def test_timeouts_stay_on_the_dependency_span(self) -> None:
        world = inject_dependency_latency(
            self.healthy,
            service="payment-service",
            dependency="paygate",
            at=self.at,
            added_ms=160,
            timeout_rate=1.0,
            seed=3,
        )
        later = [
            span
            for span in world.spans
            if span.dependency == "paygate" and span.start_time >= self.at
        ]
        self.assertTrue(all(span.status == "timeout" for span in later))
        self.assertTrue(all(span.attributes["deployment_version"] == "v2.14.2" for span in later))
        gateways = [
            span
            for span in world.spans
            if span.operation == "POST /checkout" and span.start_time >= self.at
        ]
        self.assertTrue(all(span.attributes["error_type"] == "downstream_error" for span in gateways))
        self.assertEqual(world.deployments, [])


if __name__ == "__main__":
    unittest.main()
