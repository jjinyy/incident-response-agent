"""Rank documents by keyword overlap, n-gram vectors, or both."""

from __future__ import annotations

import hashlib
import math
import re

DIM = 64


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def keyword_scores(query: str, documents: list[tuple[str, str]]) -> dict[str, float]:
    query_tokens = set(tokenize(query))
    if not query_tokens:
        return {}
    scores = {}
    for doc_id, text in documents:
        doc_tokens = set(tokenize(text))
        if not doc_tokens:
            continue
        overlap = len(query_tokens & doc_tokens) / len(query_tokens)
        if overlap > 0:
            scores[doc_id] = overlap
    return scores


def embed(text: str) -> tuple[float, ...]:
    buckets = [0.0] * DIM
    folded = re.sub(r"\s+", " ", text.casefold()).strip()
    padded = f"  {folded}  "
    for index in range(len(padded) - 2):
        gram = padded[index : index + 3]
        digest = hashlib.sha256(gram.encode("utf-8")).digest()
        buckets[digest[0] % DIM] += 1.0
    norm = math.sqrt(sum(value * value for value in buckets))
    if norm == 0:
        return tuple(buckets)
    return tuple(value / norm for value in buckets)


def cosine_scores(query: str, documents: list[tuple[str, str]]) -> dict[str, float]:
    query_vector = embed(query)
    scores = {}
    for doc_id, text in documents:
        scores[doc_id] = _cosine(query_vector, embed(text))
    return scores


def fuse(keyword: dict[str, float], vector: dict[str, float]) -> dict[str, float]:
    """Equal-weight sum. A missing keyword score counts as 0."""
    scores = {}
    for doc_id in set(keyword) | set(vector):
        scores[doc_id] = 0.5 * keyword.get(doc_id, 0.0) + 0.5 * vector.get(doc_id, 0.0)
    return scores


def rank(scores: dict[str, float], limit: int) -> list[str]:
    ordered = sorted(scores, key=lambda doc_id: (-scores[doc_id], doc_id))
    return ordered[:limit]


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(a * b for a, b in zip(left, right))
