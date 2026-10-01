"""Baseline investigation loop. The model picks tools; this code runs them."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from incident_agent.agent.baseline import BASELINE_PROMPT, TOOLS
from incident_agent.agent.executor import execute_tool
from incident_agent.agent.report import validate_report
from incident_agent.approval.actions import ActionProposal
from incident_agent.llm.provider import LLMResponse, Provider
from incident_agent.world.telemetry import WorldSlice

MAX_ITERATIONS = 8
MAX_TOOL_CALLS = 16


@dataclass
class Investigation:
    report: dict | None
    proposals: list[ActionProposal]
    events: list[dict] = field(default_factory=list)
    tool_calls: int = 0


def investigate(world: WorldSlice, incident: str, provider: Provider) -> Investigation:
    messages: list[dict] = [
        {"role": "system", "content": BASELINE_PROMPT},
        {"role": "user", "content": incident},
    ]
    proposals: list[ActionProposal] = []
    evidence_ids: set[str] = set()
    events: list[dict] = []
    seen: dict[str, dict] = {}
    tool_calls = 0
    report = None

    for _ in range(MAX_ITERATIONS):
        response = provider.complete(messages, TOOLS)
        events.append(_llm_event(response))
        if not response.tool_calls:
            messages.append(
                {
                    "role": "user",
                    "content": "Call a tool or submit_incident_report.",
                }
            )
            continue

        messages.append(_assistant_message(response))
        for call in response.tool_calls:
            if tool_calls >= MAX_TOOL_CALLS:
                events.append({"type": "stopped", "reason": "max_tool_calls"})
                return Investigation(report, proposals, events, tool_calls)
            tool_calls += 1
            key = json.dumps({"name": call.name, "arguments": call.arguments}, sort_keys=True)
            if call.name == "submit_incident_report":
                errors = validate_report(
                    call.arguments,
                    evidence_ids,
                    {item.action_id for item in proposals},
                )
                result = {"ok": not errors, "errors": errors, "evidence_ids": [], "records": []}
                if not errors:
                    report = call.arguments
            elif key in seen:
                result = seen[key]
            else:
                result = execute_tool(world, proposals, call)
                seen[key] = result
                evidence_ids.update(result.get("evidence_ids", []))
            events.append(
                {
                    "type": "tool_call",
                    "name": call.name,
                    "arguments": call.arguments,
                    "evidence_ids": result.get("evidence_ids", []),
                    "ok": result.get("ok", False),
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result),
                }
            )
            if report is not None:
                return Investigation(report, proposals, events, tool_calls)

    events.append({"type": "stopped", "reason": "max_iterations"})
    return Investigation(report, proposals, events, tool_calls)


def _assistant_message(response: LLMResponse) -> dict:
    return {
        "role": "assistant",
        "content": response.content,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments),
                },
            }
            for call in response.tool_calls
        ],
    }


def _llm_event(response: LLMResponse) -> dict:
    return {
        "type": "llm_call",
        "model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "tool_names": [call.name for call in response.tool_calls],
    }


def proposal_dicts(result: Investigation) -> list[dict]:
    return [asdict(item) for item in result.proposals]
