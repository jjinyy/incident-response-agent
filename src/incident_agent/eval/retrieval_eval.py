"""Compare keyword-only search with keyword plus n-gram vectors."""

from __future__ import annotations

from incident_agent.retrieval.fusion import cosine_scores, fuse, keyword_scores, rank
from incident_agent.world.catalog import INCIDENTS, RUNBOOKS

LABELED = (
    ("runbook", "roll back the previous payment version", "rb-deploy-regression"),
    ("runbook", "paygate latency and flat cpu", "rb-paygate-latency"),
    ("runbook", "postgres pool exhaustion", "rb-pool"),
    ("runbook", "feature flag config change", "rb-config"),
    ("incident", "payment deploy rollback", "inc-pay-2024"),
    ("incident", "paygate timeout latency", "inc-paygate-2025"),
    ("incident", "order pool saturation", "inc-pool-2024"),
    ("incident", "require amount flag", "inc-flag-2025"),
)


def evaluate_retrieval(limit: int = 5) -> dict:
    documents = _documents()
    return {
        "limit": limit,
        "documents": len(documents),
        "labeled_queries": len(LABELED),
        "embedder": "hashed-character-trigram",
        "keyword": _metrics("keyword", documents, limit),
        "hybrid": _metrics("hybrid", documents, limit),
    }


def _metrics(mode: str, documents: dict[str, list[tuple[str, str]]], limit: int) -> dict:
    reciprocal_ranks = []
    hits_at_limit = 0
    for kind, query, expected in LABELED:
        ordered = _search(mode, query, documents[kind], limit)
        if expected in ordered:
            hits_at_limit += 1
            reciprocal_ranks.append(1 / (ordered.index(expected) + 1))
        else:
            reciprocal_ranks.append(0.0)
    count = len(LABELED)
    return {
        "recall_at_1": sum(rank == 1.0 for rank in reciprocal_ranks) / count,
        "recall_at_k": hits_at_limit / count,
        "mrr": sum(reciprocal_ranks) / count,
    }


def _search(mode: str, query: str, documents: list[tuple[str, str]], limit: int) -> list[str]:
    keyword = keyword_scores(query, documents)
    if mode == "keyword":
        return rank(keyword, limit)
    if mode == "hybrid":
        return rank(fuse(keyword, cosine_scores(query, documents)), limit)
    raise ValueError("mode must be keyword or hybrid")


def _documents() -> dict[str, list[tuple[str, str]]]:
    return {
        "runbook": [(item.runbook_id, f"{item.title}\n{item.body}") for item in RUNBOOKS],
        "incident": [
            (item.incident_id, f"{item.title}\n{item.summary}\n{item.root_cause_label}")
            for item in INCIDENTS
        ],
    }
