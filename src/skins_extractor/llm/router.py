"""Routes LLM calls to the right provider based on profile config."""

from __future__ import annotations

import logging
from typing import Any

from ..config import ProfileConfig
from ..models import ExtractedActor, OutlineResult, SectionContext

logger = logging.getLogger(__name__)


def build_provider(cfg: Any) -> Any:
    provider = cfg.provider.lower()
    if provider == "anthropic":
        from .anthropic_adapter import AnthropicAdapter

        return AnthropicAdapter(
            model=cfg.model,
            enable_caching=getattr(cfg, "enable_caching", False),
            max_tokens=cfg.max_tokens,
        )
    elif provider == "openai":
        from .openai_adapter import OpenAIAdapter

        return OpenAIAdapter(model=cfg.model, max_tokens=cfg.max_tokens)
    elif provider == "google":
        from .google_adapter import GoogleAdapter

        return GoogleAdapter(model=cfg.model, max_tokens=cfg.max_tokens)
    elif provider == "xai":
        from .xai_adapter import XAIAdapter

        return XAIAdapter(model=cfg.model, max_tokens=cfg.max_tokens)
    else:
        raise ValueError(f"Unknown LLM provider: {provider!r}")


class _OutlineResponse(OutlineResult):
    """Pydantic model passed to complete_json for structured outline."""

    pass


class LLMRouter:
    def __init__(self, profile: ProfileConfig) -> None:
        self._outliner_provider = build_provider(profile.outliner)
        self._row_fallback_provider = build_provider(profile.row_fallback)
        self._vision_provider = build_provider(profile.vision_fallback)

    def outline(self, system: str, user: str) -> OutlineResult:
        result = self._outliner_provider.complete_json(
            system=system,
            user=user,
            schema=OutlineResult,
            cache_system=True,
        )
        return result  # type: ignore[return-value]

    def fill_section(
        self,
        system: str,
        user: str,
        context: SectionContext,
        partial_actors: list[ExtractedActor],
    ) -> list[ExtractedActor]:
        from pydantic import BaseModel

        class ActorList(BaseModel):
            actors: list[dict]

        result = self._row_fallback_provider.complete_json(
            system=system,
            user=user,
            schema=ActorList,
            cache_system=True,
        )

        from ..extractors.llm_extractor import actors_from_llm_response

        actor_list: ActorList = result  # type: ignore[assignment]
        return actors_from_llm_response(actor_list.actors, source="llm-row-fallback")

    def vision_ocr(self, page_image: bytes) -> str:
        from pydantic import BaseModel

        class VisionResult(BaseModel):
            extracted_text: str

        system = "Extract all text from this image of a production roster. Return the raw text."
        result = self._vision_provider.complete_vision_json(
            system=system,
            user="Please extract all text from this image.",
            image_bytes=page_image,
            schema=VisionResult,
        )
        vision_result: VisionResult = result  # type: ignore[assignment]
        return vision_result.extracted_text
