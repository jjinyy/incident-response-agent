import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from incident_agent.eval.retrieval_eval import evaluate_retrieval
from incident_agent.retrieval.fusion import fuse, rank
from incident_agent.world.catalog import with_catalog
from incident_agent.world.telemetry import generate_healthy_checkouts
from incident_agent.tools.knowledge import search_runbooks


class RetrievalTests(unittest.TestCase):
    def test_vector_score_breaks_a_keyword_tie(self) -> None:
        keyword = {"a-wrong": 0.5, "b-right": 0.5}
        vector = {"a-wrong": 0.1, "b-right": 0.9}
        self.assertEqual(rank(keyword, 1), ["a-wrong"])
        self.assertEqual(rank(fuse(keyword, vector), 1), ["b-right"])

    def test_catalog_metrics_are_computed_for_both_modes(self) -> None:
        report = evaluate_retrieval(limit=5)
        self.assertEqual(report["embedder"], "hashed-character-trigram")
        self.assertEqual(report["labeled_queries"], 8)
        for mode in ("keyword", "hybrid"):
            self.assertGreaterEqual(report[mode]["recall_at_1"], 0.0)
            self.assertLessEqual(report[mode]["recall_at_1"], 1.0)
            self.assertGreaterEqual(report[mode]["recall_at_k"], 0.0)
            self.assertLessEqual(report[mode]["recall_at_k"], 1.0)
            self.assertGreaterEqual(report[mode]["mrr"], 0.0)
            self.assertLessEqual(report[mode]["mrr"], 1.0)
        self.assertGreater(report["hybrid"]["recall_at_k"], 0.0)

    def test_hybrid_search_still_finds_the_rollback_runbook(self) -> None:
        world = with_catalog(generate_healthy_checkouts(1))
        records = search_runbooks(world, "roll back")
        self.assertIn("rb-deploy-regression", [item.runbook_id for item in records])


if __name__ == "__main__":
    unittest.main()
