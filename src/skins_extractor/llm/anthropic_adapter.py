"""Anthropic adapter using tool-use for structured JSON output."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class AnthropicAdapter:
    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        enable_caching: bool = True,
        max_tokens: int = 4096,
    ) -> None:
        self.model = model
        self.enable_caching = enable_caching
        self.max_tokens = max_tokens
        self._client = self._build_client()

    def _build_client(self) -> Any:
        import anthropic

        return anthropic.Anthropic()

    def complete_json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        cache_system: bool = True,
        max_tokens: int | None = None,
    ) -> BaseModel:

        max_tok = max_tokens or self.max_tokens
        tool_name = schema.__name__
        tool_schema = schema.model_json_schema()

        system_content: list[dict[str, Any]] = [{"type": "text", "text": system}]
        if self.enable_caching and cache_system:
            system_content[0]["cache_control"] = {"type": "ephemeral"}  # type: ignore[index]

        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tok,
            system=system_content,
            tools=[
                {
                    "name": tool_name,
                    "description": f"Extract data matching the {tool_name} schema.",
                    "input_schema": tool_schema,
                }
            ],
            tool_choice={"type": "tool", "name": tool_name},
            messages=[{"role": "user", "content": user}],
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == tool_name:
                return schema.model_validate(block.input)

        raise ValueError(f"No tool_use block in Anthropic response: {response.content}")

    def complete_vision_json(
        self,
        system: str,
        user: str,
        image_bytes: bytes,
        schema: type[BaseModel],
        max_tokens: int = 4096,
    ) -> BaseModel:
        import base64

        tool_name = schema.__name__
        tool_schema = schema.model_json_schema()
        image_b64 = base64.standard_b64encode(image_bytes).decode()

        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            tools=[
                {
                    "name": tool_name,
                    "description": f"Extract data matching the {tool_name} schema.",
                    "input_schema": tool_schema,
                }
            ],
            tool_choice={"type": "tool", "name": tool_name},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": user},
                    ],
                }
            ],
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == tool_name:
                return schema.model_validate(block.input)

        raise ValueError("No tool_use block in vision response")
