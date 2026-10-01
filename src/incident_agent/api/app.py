"""HTTP entry points for one active synthetic incident."""

from __future__ import annotations

import os
from dataclasses import asdict
from datetime import datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from incident_agent.agent.orchestrator import investigate
from incident_agent.api.scenarios import SCENARIOS, build_scenario
from incident_agent.eval.runner import run_eval
from incident_agent.eval.scenarios import all_scenarios
from incident_agent.approval.actions import approve_action, reject_action
from incident_agent.llm.openai_provider import OpenAIProvider
from incident_agent.llm.provider import Provider
from incident_agent.tools.metrics import TimeRange
from incident_agent.tools.services import get_service_health


class CreateIncident(BaseModel):
    description: str
    scenario: str


class Store:
    def __init__(self) -> None:
        self.incidents: dict[str, dict] = {}
        self.actions: dict[str, dict] = {}
        self.active_incident_id: str | None = None
        self._incident_n = 0
        self._action_n = 0

    def next_incident_id(self) -> str:
        self._incident_n += 1
        return f"inc-{self._incident_n}"

    def next_action_id(self) -> str:
        self._action_n += 1
        return f"act-{self._action_n}"


def create_app(provider: Provider | None = None) -> FastAPI:
    app = FastAPI(title="incident-response-agent")
    app.state.store = Store()
    app.state.provider = provider

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/incidents", status_code=201)
    def create_incident(body: CreateIncident) -> dict:
        try:
            world = build_scenario(body.scenario)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        store: Store = app.state.store
        incident_id = store.next_incident_id()
        store.incidents[incident_id] = {
            "incident_id": incident_id,
            "description": body.description,
            "scenario": body.scenario,
            "world": world,
            "report": None,
            "events": [],
        }
        store.active_incident_id = incident_id
        return _incident_body(store.incidents[incident_id])

    @app.get("/incidents/{incident_id}")
    def get_incident(incident_id: str) -> dict:
        return _incident_body(_require_incident(app, incident_id))

    @app.post("/incidents/{incident_id}/investigate")
    def investigate_incident(incident_id: str) -> dict:
        record = _require_incident(app, incident_id)
        provider_impl = app.state.provider or OpenAIProvider(
            os.environ.get("OPENAI_MODEL", "gpt-4.1")
        )
        try:
            result = investigate(record["world"], record["description"], provider_impl)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        record["report"] = result.report
        record["events"] = result.events
        actions = []
        for proposal in result.proposals:
            action_id = app.state.store.next_action_id()
            app.state.store.actions[action_id] = {
                "id": action_id,
                "incident_id": incident_id,
                "proposal": proposal,
            }
            actions.append(_action_body(app.state.store.actions[action_id]))
        return {"incident_id": incident_id, "report": result.report, "actions": actions}

    @app.get("/incidents/{incident_id}/trace")
    def get_trace(incident_id: str) -> dict:
        record = _require_incident(app, incident_id)
        return {"incident_id": incident_id, "events": record["events"]}

    @app.get("/actions")
    def list_actions() -> dict:
        return {"actions": [_action_body(item) for item in app.state.store.actions.values()]}

    @app.post("/actions/{action_id}/approve")
    def approve(action_id: str) -> dict:
        return _settle(app, action_id, approve=True)

    @app.post("/actions/{action_id}/reject")
    def reject(action_id: str) -> dict:
        return _settle(app, action_id, approve=False)

    @app.get("/services/{service_name}/health")
    def service_health(service_name: str, start: str, end: str) -> dict:
        record = _active_incident(app)
        try:
            health = get_service_health(
                record["world"],
                service_name,
                TimeRange(_parse_time(start), _parse_time(end)),
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return asdict(health)

    @app.post("/eval/run")
    def eval_run(limit: int = 1, split: str | None = None) -> dict:
        provider_impl = app.state.provider or OpenAIProvider(
            os.environ.get("OPENAI_MODEL", "gpt-4.1")
        )
        selected = all_scenarios()
        if split is not None:
            if split not in {"analysis", "holdout"}:
                raise HTTPException(400, "split must be analysis or holdout")
            selected = [item for item in selected if item["split"] == split]
        if limit < 1:
            raise HTTPException(400, "limit must be >= 1")
        try:
            return run_eval(provider_impl, selected[:limit])
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    return app


def _settle(app: FastAPI, action_id: str, approve: bool) -> dict:
    stored = app.state.store.actions.get(action_id)
    if stored is None:
        raise HTTPException(404, "unknown action")
    incident = _require_incident(app, stored["incident_id"])
    try:
        if approve:
            world, proposal = approve_action(incident["world"], stored["proposal"])
            incident["world"] = world
        else:
            proposal = reject_action(stored["proposal"])
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    stored["proposal"] = proposal
    return _action_body(stored)


def _require_incident(app: FastAPI, incident_id: str) -> dict:
    record = app.state.store.incidents.get(incident_id)
    if record is None:
        raise HTTPException(404, "unknown incident")
    return record


def _active_incident(app: FastAPI) -> dict:
    incident_id = app.state.store.active_incident_id
    if incident_id is None:
        raise HTTPException(404, "no active incident")
    return _require_incident(app, incident_id)


def _incident_body(record: dict) -> dict:
    return {
        "incident_id": record["incident_id"],
        "description": record["description"],
        "scenario": record["scenario"],
        "scenarios": list(SCENARIOS),
        "report": record["report"],
    }


def _action_body(stored: dict) -> dict:
    proposal = stored["proposal"]
    return {
        "id": stored["id"],
        "incident_id": stored["incident_id"],
        "action": proposal.action,
        "service": proposal.service,
        "at": proposal.at.isoformat(),
        "target_version": proposal.target_version,
        "risk": proposal.risk,
        "status": proposal.status,
    }


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise HTTPException(400, "timestamp must be timezone-aware")
    return parsed


app = create_app()
