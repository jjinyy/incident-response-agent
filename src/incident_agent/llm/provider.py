"""LLM responses shared by the real provider and tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    tool_calls: list[ToolCall] = field(default_factory=list)
    content: str | None = None
    model: str = "fake"
    input_tokens: int | None = None
    output_tokens: int | None = None


class Provider(Protocol):
    def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        """Return the next tool calls or an empty tool list."""
