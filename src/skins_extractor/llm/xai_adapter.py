"""xAI adapter — OpenAI-compatible API."""

from __future__ import annotations

import logging
import os
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class XAIAdapter:
    def __init__(
        self,
        model: str = "grok-3-fast",
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        import openai

        self._client = openai.OpenAI(
            api_key=os.environ.get("XAI_API_KEY", ""),
            base_url="https://api.x.ai/v1",
        )

    def complete_json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        cache_system: bool = True,
        max_tokens: int | None = None,
    ) -> BaseModel:

        max_tok = max_tokens or self.max_tokens
        schema_json = schema.model_json_schema()

        response = self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tok,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "strict": True, "schema": schema_json},
            },
        )

        content = response.choices[0].message.content or "{}"
        return schema.model_validate_json(content)

    def complete_vision_json(
        self,
        system: str,
        user: str,
        image_bytes: bytes,
        schema: type[BaseModel],
        max_tokens: int = 4096,
    ) -> BaseModel:
        import base64

        image_b64 = base64.standard_b64encode(image_bytes).decode()
        schema_json = schema.model_json_schema()

        response = self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                        {"type": "text", "text": user},
                    ],
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "strict": True, "schema": schema_json},
            },
        )

        content = response.choices[0].message.content or "{}"
        return schema.model_validate_json(content)
