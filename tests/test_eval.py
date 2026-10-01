import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from incident_agent.agent.orchestrator import Investigation
from incident_agent.api.scenarios import SCENARIO_FAULT_AT
from incident_agent.approval.actions import propose_action
from incident_agent.eval.recovery import verify_recovery
from incident_agent.eval.scenarios import all_scenarios, build_world
from incident_agent.eval.score import score_scenario
from incident_agent.world.telemetry import BASE_VERSIONS


class EvalScenarioTests(unittest.TestCase):
    def test_dataset_has_36_scenarios_and_a_fixed_split(self) -> None:
        scenarios = all_scenarios()
        self.assertEqual(len(scenarios), 36)
        self.assertEqual(len({item["id"] for item in scenarios}), 36)
        self.assertEqual(sum(item["split"] == "analysis" for item in scenarios), 24)
        self.assertEqual(sum(item["split"] == "holdout" for item in scenarios), 12)
        for scenario in scenarios:
            world = build_world(scenario)
            self.assertTrue(world.spans)

    def test_matching_report_scores_higher_than_a_wrong_cause(self) -> None:
        scenario = all_scenarios()[0]
        good = score_scenario(scenario, _result(scenario, "deployment_regression"))
        bad = score_scenario(scenario, _result(scenario, "traffic_spike"))
        self.assertEqual(good["root_cause_accuracy"], 1)
        self.assertEqual(good["tool_selection_recall"], 1)
        self.assertEqual(good["evidence_grounding"], 1)
        self.assertEqual(good["remediation_accuracy"], 1)
        self.assertEqual(good["action_safety"], 1)
        self.assertEqual(bad["root_cause_accuracy"], 0)

    def test_forbidden_rollback_fails_remediation(self) -> None:
        scenario = next(item for item in all_scenarios() if item["kind"] == "pool")
        scored = score_scenario(scenario, _result(scenario, scenario["category"], action="rollback_deployment"))
        self.assertEqual(scored["remediation_accuracy"], 0)

    def test_harness_replay_restores_the_previous_payment_version(self) -> None:
        scenario = next(item for item in all_scenarios() if item["kind"] == "deploy")
        world = build_world(scenario)
        proposal = propose_action(
            action="rollback_deployment",
            service=scenario["service"],
            at=SCENARIO_FAULT_AT,
            target_version=BASE_VERSIONS[scenario["service"]],
        )
        checked = verify_recovery(scenario, world, Investigation(None, [proposal], [], 0))
        self.assertEqual(checked["recovery_verification"], 1.0)
        self.assertEqual(checked["recovery_approved_by"], "eval_harness")
        self.assertEqual(proposal.status, "PENDING_APPROVAL")

    def test_wrong_rollback_version_stays_unrecovered(self) -> None:
        scenario = next(item for item in all_scenarios() if item["kind"] == "deploy")
        world = build_world(scenario)
        proposal = propose_action(
            action="rollback_deployment",
            service=scenario["service"],
            at=SCENARIO_FAULT_AT,
            target_version="v0.0.1",
        )
        checked = verify_recovery(scenario, world, Investigation(None, [proposal], [], 0))
        self.assertEqual(checked["recovery_verification"], 0.0)
        self.assertEqual(checked["recovery_approved_by"], "eval_harness")

    def test_scenarios_without_an_acceptable_action_skip_recovery(self) -> None:
        scenario = next(item for item in all_scenarios() if item["kind"] == "pool")
        world = build_world(scenario)
        checked = verify_recovery(scenario, world, Investigation(None, [], [], 0))
        self.assertIsNone(checked["recovery_verification"])


def _result(scenario: dict, category: str, action: str = "rollback_deployment") -> Investigation:
    evidence = {
        "metric": "metric:api-gateway:error_rate:-:t",
        "deployment": "deployment:payment-service:v9.0:t",
        "log": "log:span-1",
        "dependency": "dependency:order-service:postgres:t",
        "config": "config:payment-service:payments.require_amount:t",
    }
    events = []
    for name, prefix in (
        ("get_service_metrics", "metric"),
        ("get_recent_deployments", "deployment"),
        ("search_logs", "log"),
        ("get_dependency_health", "dependency"),
        ("get_configuration_changes", "config"),
        ("search_traces", "trace"),
    ):
        events.append(
            {
                "type": "tool_call",
                "name": name,
                "evidence_ids": [evidence[prefix]] if prefix in evidence else ["trace:trace-0005"],
            }
        )
    cited = [evidence[prefix] for prefix in scenario["evidence_prefixes"]]
    report = {
        "status": scenario["status"] if category == scenario["category"] else "ROOT_CAUSE_IDENTIFIED",
        "root_cause": {
            "category": category,
            "service": scenario["service"],
            "statement": "scored from cited evidence",
            "evidence_ids": cited or ["metric:missing"],
        },
        "observations": [],
    }
    if scenario["status"] != "ROOT_CAUSE_IDENTIFIED" and category == scenario["category"]:
        report["status"] = scenario["status"]
        report["root_cause"] = None
    proposal = propose_action(
        action=action,
        service=scenario["service"] or "payment-service",
        at=datetime(2026, 3, 12, 14, 5, tzinfo=timezone.utc),
        target_version="v2.14.2" if action == "rollback_deployment" else None,
    )
    return Investigation(report, [proposal], events, tool_calls=len(events))


if __name__ == "__main__":
    unittest.main()
