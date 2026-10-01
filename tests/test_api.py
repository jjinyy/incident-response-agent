import sys
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient

from incident_agent.api.app import create_app
from incident_agent.api.scenarios import SCENARIO_FAULT_AT, SCENARIO_START
from incident_agent.llm.provider import LLMResponse, ToolCall


class RestartScript:
    def __init__(self) -> None:
        self.step = 0

    def complete(self, messages, tools) -> LLMResponse:
        self.step += 1
        if self.step == 1:
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        "propose",
                        "propose_action",
                        {
                            "action": "restart_service",
                            "service": "payment-service",
                            "at": SCENARIO_FAULT_AT.isoformat(),
                        },
                    )
                ]
            )
        return LLMResponse(
            tool_calls=[
                ToolCall(
                    "submit",
                    "submit_incident_report",
                    {
                        "incident_summary": "Restart was requested before the cause was settled.",
                        "severity": "sev3",
                        "status": "INSUFFICIENT_EVIDENCE",
                        "affected_services": ["payment-service"],
                        "observations": [],
                        "root_cause": None,
                        "proposed_action_ids": [],
                        "missing_information": ["restart does not explain the 5xx"],
                    },
                )
            ]
        )


class ApiTests(unittest.TestCase):
    def test_investigate_then_approve_rollback(self) -> None:
        from tests.test_baseline_agent import DeployScript

        client = TestClient(
            create_app(
                DeployScript(
                    SCENARIO_START,
                    SCENARIO_START + timedelta(minutes=10),
                    SCENARIO_FAULT_AT,
                )
            )
        )
        created = client.post(
            "/incidents",
            json={
                "description": "Checkout 5xx increased. Find the cause.",
                "scenario": "payment_deploy_regression",
            },
        )
        self.assertEqual(created.status_code, 201)
        incident_id = created.json()["incident_id"]

        investigated = client.post(f"/incidents/{incident_id}/investigate")
        self.assertEqual(investigated.status_code, 200)
        body = investigated.json()
        self.assertEqual(body["report"]["root_cause"]["category"], "deployment_regression")
        action_id = body["actions"][0]["id"]
        self.assertEqual(body["actions"][0]["status"], "PENDING_APPROVAL")

        window = {
            "start": SCENARIO_FAULT_AT.isoformat(),
            "end": (SCENARIO_FAULT_AT + timedelta(minutes=5)).isoformat(),
        }
        before = client.get("/services/api-gateway/health", params=window)
        self.assertEqual(before.status_code, 200)
        self.assertEqual(before.json()["error_rate"], 1.0)

        approved = client.post(f"/actions/{action_id}/approve")
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "EXECUTED")
        after = client.get("/services/api-gateway/health", params=window)
        self.assertEqual(after.json()["error_rate"], 0.0)

        trace = client.get(f"/incidents/{incident_id}/trace")
        names = [event["name"] for event in trace.json()["events"] if event["type"] == "tool_call"]
        self.assertIn("get_recent_deployments", names)

    def test_reject_leaves_the_fault(self) -> None:
        client = TestClient(create_app(RestartScript()))
        created = client.post(
            "/incidents",
            json={
                "description": "Please restart payment.",
                "scenario": "payment_deploy_regression",
            },
        )
        incident_id = created.json()["incident_id"]
        investigated = client.post(f"/incidents/{incident_id}/investigate")
        action_id = investigated.json()["actions"][0]["id"]
        rejected = client.post(f"/actions/{action_id}/reject")
        self.assertEqual(rejected.json()["status"], "REJECTED")
        window = {
            "start": SCENARIO_FAULT_AT.isoformat(),
            "end": (SCENARIO_FAULT_AT + timedelta(minutes=5)).isoformat(),
        }
        health = client.get("/services/api-gateway/health", params=window)
        self.assertEqual(health.json()["error_rate"], 1.0)

    def test_eval_runs_one_scenario_with_the_scripted_provider(self) -> None:
        from datetime import timedelta

        from tests.test_baseline_agent import DeployScript

        client = TestClient(
            create_app(
                DeployScript(
                    SCENARIO_START,
                    SCENARIO_START + timedelta(minutes=10),
                    SCENARIO_FAULT_AT,
                )
            )
        )
        response = client.post("/eval/run", params={"limit": 1})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["scenarios"], 1)
        self.assertEqual(body["rows"][0]["root_cause_accuracy"], 1)
        self.assertEqual(body["rows"][0]["recovery_verification"], 1.0)
        self.assertEqual(body["rows"][0]["recovery_approved_by"], "eval_harness")
        self.assertEqual(client.get("/health").json()["status"], "ok")


if __name__ == "__main__":
    unittest.main()
