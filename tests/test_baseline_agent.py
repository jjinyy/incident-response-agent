import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from incident_agent.agent.orchestrator import investigate
from incident_agent.llm.provider import LLMResponse, ToolCall
from incident_agent.world.faults import inject_deployment_regression
from incident_agent.world.telemetry import generate_healthy_checkouts


def _calls(response_calls: list[tuple[str, str, dict]]) -> LLMResponse:
    return LLMResponse(
        tool_calls=[ToolCall(call_id, name, arguments) for call_id, name, arguments in response_calls]
    )


class DeployScript:
    def __init__(self, start: datetime, end: datetime, action_at: datetime) -> None:
        self.step = 0
        self.window = {"start": start.isoformat(), "end": end.isoformat()}
        self.action_at = action_at.isoformat()

    def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        self.step += 1
        if self.step == 1:
            return _calls(
                [
                    (
                        "metrics",
                        "get_service_metrics",
                        {
                            "service_name": "api-gateway",
                            "metric_names": ["error_rate"],
                            "time_range": self.window,
                        },
                    )
                ]
            )
        if self.step == 2:
            return _calls(
                [
                    (
                        "deploys",
                        "get_recent_deployments",
                        {"service_name": "payment-service", "time_range": self.window},
                    )
                ]
            )
        if self.step == 3:
            return _calls(
                [
                    (
                        "logs",
                        "search_logs",
                        {
                            "service_name": "payment-service",
                            "query": "NullAmount",
                            "time_range": self.window,
                        },
                    )
                ]
            )
        if self.step == 4:
            return _calls(
                [
                    (
                        "propose",
                        "propose_action",
                        {
                            "action": "rollback_deployment",
                            "service": "payment-service",
                            "at": self.action_at,
                            "target_version": "v2.14.2",
                        },
                    )
                ]
            )
        evidence = _ids_with_prefix(messages)
        action_id = _action_id(messages)
        return _calls(
            [
                (
                    "submit",
                    "submit_incident_report",
                    {
                        "incident_summary": "Payment 5xx started after v2.14.3.",
                        "severity": "sev2",
                        "status": "ROOT_CAUSE_IDENTIFIED",
                        "affected_services": ["payment-service", "api-gateway"],
                        "observations": [
                            {
                                "statement": "Gateway error rate rose after the deploy.",
                                "evidence_ids": [evidence["metric"], evidence["deployment"]],
                            }
                        ],
                        "root_cause": {
                            "category": "deployment_regression",
                            "service": "payment-service",
                            "statement": "v2.14.3 introduced NullAmount errors.",
                            "evidence_ids": [
                                evidence["metric"],
                                evidence["deployment"],
                                evidence["log"],
                            ],
                        },
                        "proposed_action_ids": [action_id],
                        "missing_information": [],
                    },
                )
            ]
        )


class InsufficientScript:
    def __init__(self) -> None:
        self.step = 0

    def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        self.step += 1
        if self.step == 1:
            report = _insufficient()
            report["observations"] = [
                {"statement": "guess", "evidence_ids": ["metric:missing"]}
            ]
            report["status"] = "ROOT_CAUSE_IDENTIFIED"
            report["root_cause"] = {
                "category": "deployment_regression",
                "service": "payment-service",
                "statement": "guess",
                "evidence_ids": ["metric:missing"],
            }
            return _calls([("bad", "submit_incident_report", report)])
        return _calls([("ok", "submit_incident_report", _insufficient())])


class BaselineAgentTests(unittest.TestCase):
    def test_scripted_investigation_cites_tools_and_does_not_roll_back(self) -> None:
        start = datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc)
        deployed_at = start + timedelta(minutes=5)
        world = inject_deployment_regression(
            generate_healthy_checkouts(10, start=start, spacing_seconds=60),
            service="payment-service",
            version="v2.14.3",
            at=deployed_at,
            error_rate=1.0,
            error_type="NullAmount",
            seed=1,
        )
        before = [(point.name, point.bucket_start, point.value) for point in world.metrics]
        result = investigate(
            world,
            "Checkout 5xx increased. Find the cause.",
            DeployScript(start, start + timedelta(minutes=10), deployed_at),
        )
        after = [(point.name, point.bucket_start, point.value) for point in world.metrics]

        self.assertEqual(before, after)
        self.assertEqual(result.report["status"], "ROOT_CAUSE_IDENTIFIED")
        self.assertEqual(result.report["root_cause"]["category"], "deployment_regression")
        self.assertEqual(len(result.proposals), 1)
        self.assertEqual(result.proposals[0].status, "PENDING_APPROVAL")
        self.assertEqual(result.proposals[0].action, "rollback_deployment")
        names = [event["name"] for event in result.events if event["type"] == "tool_call"]
        self.assertEqual(
            names,
            [
                "get_service_metrics",
                "get_recent_deployments",
                "search_logs",
                "propose_action",
                "submit_incident_report",
            ],
        )

    def test_unknown_evidence_is_rejected_then_insufficient_is_accepted(self) -> None:
        start = datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc)
        world = generate_healthy_checkouts(1, start=start)
        result = investigate(world, "Something feels slow.", InsufficientScript())
        self.assertEqual(result.report["status"], "INSUFFICIENT_EVIDENCE")
        self.assertIsNone(result.report["root_cause"])
        self.assertEqual(result.proposals, [])
        submits = [
            event for event in result.events if event.get("name") == "submit_incident_report"
        ]
        self.assertEqual([event["ok"] for event in submits], [False, True])


def _insufficient() -> dict:
    return {
        "incident_summary": "Not enough evidence.",
        "severity": "sev3",
        "status": "INSUFFICIENT_EVIDENCE",
        "affected_services": [],
        "observations": [],
        "root_cause": None,
        "proposed_action_ids": [],
        "missing_information": ["no failing span or deploy was observed"],
    }


def _ids_with_prefix(messages: list[dict]) -> dict[str, str]:
    found = {}
    for message in messages:
        if message.get("role") != "tool":
            continue
        for evidence_id in json.loads(message["content"]).get("evidence_ids", []):
            found[evidence_id.split(":", 1)[0]] = evidence_id
    return found


def _action_id(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") != "tool":
            continue
        records = json.loads(message["content"]).get("records", [])
        if records and "action_id" in records[0]:
            return records[0]["action_id"]
    raise AssertionError("proposal was not recorded")


if __name__ == "__main__":
    unittest.main()
