"""LLM-based extraction: outliner + row-level fallback."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..models import (
    ExtractedActor,
    FieldExtraction,
    OutlineResult,
    SectionContext,
)

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent.parent.parent / "config" / "prompts"


class LLMExtractor:
    def __init__(self, router: object | None = None) -> None:
        self._router = router

    def outline(
        self,
        document_text: str,
        document_name: str,
        fingerprint: str,
        hints: list[SectionContext] | None = None,
    ) -> OutlineResult | None:
        if self._router is None:
            logger.info("LLM router not configured — skipping outline")
            return None

        try:
            from ..llm.router import LLMRouter

            router: LLMRouter = self._router  # type: ignore[assignment]

            system = self._load_prompt("outliner.system.md")
            user_tmpl = self._load_prompt("outliner.user.md")
            hints_json = json.dumps([h.model_dump() for h in (hints or [])], indent=2)
            numbered = _number_lines(document_text)
            user = (
                user_tmpl.replace("{{document_name}}", document_name)
                .replace("{{fingerprint}}", fingerprint)
                .replace("{{hints_json}}", hints_json)
                .replace("{{document_text}}", numbered)
            )

            result = router.outline(system, user)
            return result
        except Exception:
            logger.exception("LLM outline failed")
            return None

    def fill_section(
        self,
        section_text: str,
        context: SectionContext,
        partial_actors: list[ExtractedActor],
    ) -> list[ExtractedActor]:
        if self._router is None:
            return partial_actors

        try:
            from ..llm.router import LLMRouter

            router: LLMRouter = self._router  # type: ignore[assignment]

            system_tmpl = self._load_prompt("row_fallback.system.md")
            system = (
                system_tmpl.replace("{{role}}", context.role)
                .replace("{{role_type}}", context.role_type)
                .replace("{{call_time}}", context.call_time)
                .replace("{{union_name}}", context.union_name)
                .replace("{{rate_raw}}", context.rate_raw)
                .replace("{{column_convention}}", context.column_convention)
            )
            partial_json = json.dumps([_actor_to_dict(a) for a in partial_actors], indent=2)
            user_tmpl = self._load_prompt("row_fallback.user.md")
            user = user_tmpl.replace("{{section_text}}", section_text).replace(
                "{{partial_actors_json}}", partial_json
            )

            filled = router.fill_section(system, user, context, partial_actors)
            return filled
        except Exception:
            logger.exception("LLM row-fallback failed")
            return partial_actors

    def _load_prompt(self, filename: str) -> str:
        path = _PROMPTS_DIR / filename
        if path.exists():
            return path.read_text()
        logger.warning("Prompt file not found: %s", path)
        return ""


def _actor_to_dict(actor: ExtractedActor) -> dict:
    return {
        "actor_name": actor.actor_name.value,
        "phone": actor.phone.value,
        "email": actor.email.value,
        "notes": actor.notes.value,
        "rate_override_raw": actor.rate_override_raw.value,
        "cancelled": actor.cancelled.value,
    }


def _number_lines(text: str) -> str:
    lines = text.split("\n")
    return "\n".join(f"{i + 1:4d} | {line}" for i, line in enumerate(lines))


def actors_from_llm_response(
    raw: list[dict],
    source: str = "llm",
) -> list[ExtractedActor]:
    actors = []
    for item in raw:
        conf_map: dict = item.get("confidence", {})

        def fe(field: str, default: object = "") -> FieldExtraction:
            return FieldExtraction(
                value=item.get(field, default),
                method="llm-row-fallback",
                confidence=conf_map.get(field, 0.80),
                source=source,
            )

        actors.append(
            ExtractedActor(
                actor_name=fe("actor_name"),
                phone=fe("phone"),
                email=fe("email"),
                notes=fe("notes"),
                rate_override_raw=fe("rate_override_raw"),
                cancelled=FieldExtraction(
                    value=bool(item.get("cancelled", False)),
                    method="llm-row-fallback",
                    confidence=conf_map.get("cancelled", 0.80),
                    source=source,
                ),
            )
        )
    return actors
