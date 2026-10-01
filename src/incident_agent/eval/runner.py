"""Run the agent on scenarios and score the stored trace."""

from __future__ import annotations

from incident_agent.agent.orchestrator import investigate
from incident_agent.eval.recovery import verify_recovery
from incident_agent.eval.scenarios import all_scenarios, build_world
from incident_agent.eval.score import score_scenario, summarize
from incident_agent.llm.provider import Provider


def run_eval(provider: Provider, scenarios: list[dict] | None = None) -> dict:
    selected = all_scenarios() if scenarios is None else scenarios
    rows = []
    for scenario in selected:
        world = build_world(scenario)
        result = investigate(world, scenario["description"], provider)
        row = score_scenario(scenario, result)
        row.update(verify_recovery(scenario, world, result))
        rows.append(row)
    return summarize(rows)
