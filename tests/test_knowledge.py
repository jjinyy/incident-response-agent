import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from incident_agent.tools.knowledge import (
    get_incident_details,
    search_previous_incidents,
    search_runbooks,
)
from incident_agent.world.catalog import with_catalog
from incident_agent.world.store import load_world, save_world
from incident_agent.world.telemetry import generate_healthy_checkouts


class KnowledgeToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = with_catalog(generate_healthy_checkouts(1))

    def test_runbook_search_finds_rollback_guidance(self) -> None:
        records = search_runbooks(self.world, "roll back", mode="keyword")
        self.assertEqual(records[0].runbook_id, "rb-deploy-regression")
        self.assertEqual(records[0].evidence_id, "runbook:rb-deploy-regression")

    def test_incident_search_and_details(self) -> None:
        found = search_previous_incidents(self.world, "pool")
        self.assertEqual(found[0].incident_id, "inc-pool-2024")
        details = get_incident_details(self.world, "inc-pool-2024")
        self.assertEqual(details.root_cause_label, "db_connection_pool_exhaustion")
        with self.assertRaises(ValueError):
            get_incident_details(self.world, "missing")

    def test_catalog_survives_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "world.sqlite3"
            save_world(path, self.world)
            loaded = load_world(path)
        self.assertEqual(loaded.runbooks[0].runbook_id, "rb-deploy-regression")
        self.assertEqual(loaded.incidents[1].incident_id, "inc-paygate-2025")


if __name__ == "__main__":
    unittest.main()
