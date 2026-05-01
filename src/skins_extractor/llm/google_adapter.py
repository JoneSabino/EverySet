"""Google GenAI adapter."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class GoogleAdapter:
    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        import google.generativeai as genai  # type: ignore[import-untyped]

        self._genai = genai

    def complete_json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        cache_system: bool = True,
        max_tokens: int | None = None,
    ) -> BaseModel:
        max_tok = max_tokens or self.max_tokens

        model = self._genai.GenerativeModel(
            model_name=self.model,
            system_instruction=system,
            generation_config=self._genai.GenerationConfig(
                response_mime_type="application/json",
                response_schema=schema,
                max_output_tokens=max_tok,
            ),
        )

        response = model.generate_content(user)
        return schema.model_validate_json(response.text)

    def complete_vision_json(
        self,
        system: str,
        user: str,
        image_bytes: bytes,
        schema: type[BaseModel],
        max_tokens: int = 4096,
    ) -> BaseModel:
        import io

        import PIL.Image

        model = self._genai.GenerativeModel(
            model_name=self.model,
            system_instruction=system,
            generation_config=self._genai.GenerationConfig(
                response_mime_type="application/json",
                response_schema=schema,
                max_output_tokens=max_tokens,
            ),
        )

        img = PIL.Image.open(io.BytesIO(image_bytes))
        response = model.generate_content([img, user])
        return schema.model_validate_json(response.text)
