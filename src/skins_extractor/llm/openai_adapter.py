"""OpenAI adapter using structured output (json_schema)."""

from __future__ import annotations

import base64
import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class OpenAIAdapter:
    def __init__(
        self,
        model: str = "gpt-4o",
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        import openai

        self._client = openai.OpenAI()

    def complete_json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        cache_system: bool = True,
        max_tokens: int | None = None,
    ) -> BaseModel:
        max_tok = max_tokens or self.max_tokens

        response = self._client.beta.chat.completions.parse(
            model=self.model,
            max_tokens=max_tok,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format=schema,
        )

        result = response.choices[0].message.parsed
        if result is None:
            raise ValueError("OpenAI returned no parsed result")
        return result

    def complete_vision_json(
        self,
        system: str,
        user: str,
        image_bytes: bytes,
        schema: type[BaseModel],
        max_tokens: int = 4096,
    ) -> BaseModel:
        image_b64 = base64.standard_b64encode(image_bytes).decode()

        response = self._client.beta.chat.completions.parse(
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
            response_format=schema,
        )

        result = response.choices[0].message.parsed
        if result is None:
            raise ValueError("OpenAI vision returned no parsed result")
        return result
