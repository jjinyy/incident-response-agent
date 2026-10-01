"""Keyword and hybrid search over runbooks and past incidents."""

from __future__ import annotations

from dataclasses import dataclass

from incident_agent.retrieval.fusion import cosine_scores, fuse, keyword_scores, rank
from incident_agent.world.telemetry import HistoricalIncident, WorldSlice


@dataclass(frozen=True)
class RunbookRecord:
    evidence_id: str
    runbook_id: str
    title: str
    body: str


@dataclass(frozen=True)
class IncidentRecord:
    evidence_id: str
    incident_id: str
    title: str
    summary: str
    root_cause_label: str


def search_runbooks(
    world: WorldSlice, query: str, limit: int = 5, mode: str = "hybrid"
) -> list[RunbookRecord]:
    _check(query, limit, mode)
    documents = [(item.runbook_id, f"{item.title}\n{item.body}") for item in world.runbooks]
    by_id = {item.runbook_id: item for item in world.runbooks}
    return [
        RunbookRecord(
            evidence_id=f"runbook:{doc_id}",
            runbook_id=doc_id,
            title=by_id[doc_id].title,
            body=by_id[doc_id].body,
        )
        for doc_id in _ids(mode, query, documents, limit)
    ]


def search_previous_incidents(
    world: WorldSlice, query: str, limit: int = 5, mode: str = "hybrid"
) -> list[IncidentRecord]:
    _check(query, limit, mode)
    documents = [
        (item.incident_id, f"{item.title}\n{item.summary}\n{item.root_cause_label}")
        for item in world.incidents
    ]
    by_id = {item.incident_id: item for item in world.incidents}
    return [_incident_record(by_id[doc_id]) for doc_id in _ids(mode, query, documents, limit)]


def get_incident_details(world: WorldSlice, incident_id: str) -> IncidentRecord:
    if not incident_id:
        raise ValueError("incident_id must not be empty")
    for item in world.incidents:
        if item.incident_id == incident_id:
            return _incident_record(item)
    raise ValueError(f"unknown incident: {incident_id}")


def _ids(mode: str, query: str, documents: list[tuple[str, str]], limit: int) -> list[str]:
    keyword = keyword_scores(query, documents)
    if mode == "keyword":
        return rank(keyword, limit)
    return rank(fuse(keyword, cosine_scores(query, documents)), limit)


def _incident_record(item: HistoricalIncident) -> IncidentRecord:
    return IncidentRecord(
        evidence_id=f"incident:{item.incident_id}",
        incident_id=item.incident_id,
        title=item.title,
        summary=item.summary,
        root_cause_label=item.root_cause_label,
    )


def _check(query: str, limit: int, mode: str) -> None:
    if not query.strip():
        raise ValueError("query must not be empty")
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if mode not in {"keyword", "hybrid"}:
        raise ValueError("mode must be keyword or hybrid")
