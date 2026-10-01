import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from incident_agent.tools.config import ConfigQuery, get_configuration_changes
from incident_agent.tools.metrics import TimeRange
from incident_agent.world.faults import inject_bad_configuration
from incident_agent.world.telemetry import generate_healthy_checkouts


class GetConfigurationChangesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc)
        self.changed_at = self.start + timedelta(minutes=5)
        self.world = inject_bad_configuration(
            generate_healthy_checkouts(10, start=self.start, spacing_seconds=60),
            service="payment-service",
            at=self.changed_at,
            key="payments.require_amount",
            old_value="true",
            new_value="false",
            change_type="feature_flag",
            error_type="InvalidAmount",
            deployed_version="v2.14.2",
            deployed_at=self.start,
        )
        self.window = TimeRange(self.start, self.changed_at + timedelta(minutes=5))

    def test_returns_the_flag_change(self) -> None:
        records = get_configuration_changes(
            self.world,
            ConfigQuery(service_name="payment-service", time_range=self.window),
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].key, "payments.require_amount")
        self.assertEqual((records[0].old_value, records[0].new_value), ("true", "false"))
        self.assertEqual(records[0].change_type, "feature_flag")
        self.assertEqual(records[0].changed_at, self.changed_at)
        self.assertIn("payments.require_amount", records[0].evidence_id)

    def test_excludes_other_types_services_and_earlier_ranges(self) -> None:
        env_only = get_configuration_changes(
            self.world,
            ConfigQuery(
                service_name="payment-service",
                time_range=self.window,
                change_type="env",
            ),
        )
        other = get_configuration_changes(
            self.world,
            ConfigQuery(service_name="order-service", time_range=self.window),
        )
        before = get_configuration_changes(
            self.world,
            ConfigQuery(
                service_name="payment-service",
                time_range=TimeRange(self.start, self.changed_at),
            ),
        )
        self.assertEqual(env_only, [])
        self.assertEqual(other, [])
        self.assertEqual(before, [])


if __name__ == "__main__":
    unittest.main()
