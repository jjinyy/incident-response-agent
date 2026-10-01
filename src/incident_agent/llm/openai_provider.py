"""OpenAI tool-calling adapter. Tests use a fake provider instead."""

from __future__ import annotations

import json
import os

from incident_agent.llm.provider import LLMResponse, ToolCall


class OpenAIProvider:
    def __init__(self, model: str, api_key: str | None = None) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")

    def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai package is not installed") from exc
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        client = OpenAI(api_key=self.api_key)
        completion = client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=messages,
            tools=tools,
        )
        message = completion.choices[0].message
        usage = completion.usage
        calls = []
        for call in message.tool_calls or []:
            calls.append(
                ToolCall(
                    id=call.id,
                    name=call.function.name,
                    arguments=json.loads(call.function.arguments or "{}"),
                )
            )
        return LLMResponse(
            tool_calls=calls,
            content=message.content,
            model=self.model,
            input_tokens=None if usage is None else usage.prompt_tokens,
            output_tokens=None if usage is None else usage.completion_tokens,
        )
