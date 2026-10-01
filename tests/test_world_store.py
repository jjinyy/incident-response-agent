import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from incident_agent.world.faults import inject_bad_configuration, inject_deployment_regression
from incident_agent.world.store import load_world, save_world
from incident_agent.world.telemetry import generate_healthy_checkouts


class WorldStoreTests(unittest.TestCase):
    def test_round_trip_keeps_spans_deployments_and_metrics(self) -> None:
        start = datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc)
        world = inject_deployment_regression(
            generate_healthy_checkouts(4, start=start, spacing_seconds=60),
            service="payment-service",
            version="v2.14.3",
            at=start + timedelta(minutes=2),
            error_rate=1.0,
            error_type="NullAmount",
            seed=1,
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "world.sqlite3"
            save_world(path, world)
            loaded = load_world(path)

        self.assertEqual(
            [(span.span_id, span.status, span.attributes) for span in world.spans],
            [(span.span_id, span.status, span.attributes) for span in loaded.spans],
        )
        self.assertEqual(world.deployments[0].version, loaded.deployments[0].version)
        self.assertEqual(world.deployments[0].deployed_at, loaded.deployments[0].deployed_at)
        self.assertEqual(
            [(item.name, item.value, item.service_name) for item in world.metrics],
            [(item.name, item.value, item.service_name) for item in loaded.metrics],
        )
        self.assertEqual(len(world.logs), len(loaded.logs))
        self.assertEqual(loaded.logs[0].trace_id, world.logs[0].trace_id)

    def test_round_trip_keeps_a_config_change(self) -> None:
        start = datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc)
        world = inject_bad_configuration(
            generate_healthy_checkouts(2, start=start, spacing_seconds=60),
            service="payment-service",
            at=start + timedelta(minutes=1),
            key="payments.require_amount",
            old_value="true",
            new_value="false",
            change_type="feature_flag",
            error_type="InvalidAmount",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "world.sqlite3"
            save_world(path, world)
            loaded = load_world(path)

        self.assertEqual(loaded.config_changes[0].key, "payments.require_amount")
        self.assertEqual(loaded.config_changes[0].new_value, "false")
        self.assertEqual(loaded.config_changes[0].changed_at, world.config_changes[0].changed_at)


if __name__ == "__main__":
    unittest.main()
