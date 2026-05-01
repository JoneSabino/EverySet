"""Main extraction pipeline — wires all stages together."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from .classifier import classify_blocks, extract_section_context_from_header
from .confidence import compute_row_confidence
from .config import AppConfig
from .extractors.deterministic import extract_actors_deterministic
from .extractors.llm_extractor import LLMExtractor
from .fingerprint import compute_fingerprint
from .loaders.base import load_document
from .models import (
    ExtractedActor,
    ExtractedRow,
    ExtractionMethod,
    ExtractionRun,
    RateUnit,
    SectionContext,
    UnionName,
)
from .normalizers.name import normalize_name
from .normalizers.phone import normalize_phone
from .normalizers.rate import parse_rate
from .segmenter import segment_blocks
from .validators import validate_row
from .writers import write_clean_csv, write_debug_csv

logger = logging.getLogger(__name__)


def run_pipeline(
    input_path: str | Path,
    config: AppConfig,
    llm_extractor: LLMExtractor | None = None,
    pattern_store: object | None = None,
) -> list[ExtractedRow]:
    path = Path(input_path)
    document_name = path.name
    logger.info("Processing %s", document_name)

    # Stage 1: Load
    blocks = load_document(path, ocr_min_chars=config.pipeline.ocr_min_chars)
    if not blocks:
        logger.warning("No blocks extracted from %s", document_name)
        return []

    # Stage 2: Fingerprint
    fingerprint = compute_fingerprint(blocks)
    logger.info("Fingerprint: %s", fingerprint)

    # Stage 3: Classify blocks
    stored_patterns = None
    if pattern_store is not None:
        from .pattern_store.db import PatternStore

        ps: PatternStore = pattern_store  # type: ignore[assignment]
        stored_patterns = ps.find_by_fingerprint(fingerprint)

    classified = classify_blocks(blocks, stored_patterns)

    # Segment into sections
    sections = segment_blocks(classified)

    if not sections:
        logger.warning("No sections found in %s — trying LLM outline", document_name)
        if llm_extractor:
            document_text = "\n".join(b.text for b in blocks if b.text.strip())
            outline = llm_extractor.outline(document_text, document_name, fingerprint)
            if outline:
                if pattern_store is not None and outline.suggested_patterns:
                    from .pattern_store.db import PatternStore

                    ps_save: PatternStore = pattern_store  # type: ignore[assignment]
                    pat_status = (
                        "approved"
                        if config.pipeline.trust_mode == "auto_approve"
                        else "pending_review"
                    )
                    for proposed in outline.suggested_patterns:
                        ps_save.insert(proposed, fingerprint, status=pat_status)
                return _rows_from_outline(outline, document_name, config)
        return []

    # Detect document-level column convention from unknown column-header blocks
    _LAST_FIRST_DOC_RE = re.compile(r"\bLAST\s+FIRST\b", re.IGNORECASE)
    doc_convention = next(
        (
            "LAST FIRST"
            for cb in classified
            if cb.kind == "unknown" and _LAST_FIRST_DOC_RE.search(cb.block.text)
        ),
        "",
    )

    # Stages 4-9: Per-section processing
    all_rows: list[ExtractedRow] = []
    llm_calls = 0

    for header_block, actor_blocks, unknown_blocks in sections:
        section_ctx = extract_section_context_from_header(header_block.block)
        if not section_ctx.column_convention and doc_convention:
            section_ctx = section_ctx.model_copy(update={"column_convention": doc_convention})

        # Stage 4a: Deterministic extraction
        actors = extract_actors_deterministic(actor_blocks, section_ctx, document_name)

        # Trigger LLM fallback when any actor has no name or low name confidence
        needs_llm = any(
            not a.actor_name.value or a.actor_name.confidence < 0.5 for a in actors
        ) or (not actors and actor_blocks)

        if needs_llm and llm_extractor and actor_blocks:
            # Include unknown blocks so LLM sees data in separate PDF columns (e.g. phone numbers)
            section_text = "\n".join(cb.block.text for cb in actor_blocks + unknown_blocks)
            # Preserve deterministic inline-union detections — LLM doesn't see them
            det_union_names = [a.union_name for a in actors]
            filled = llm_extractor.fill_section(section_text, section_ctx, actors)
            # Restore by position (LLM returns same number of actors)
            for i, actor in enumerate(filled):
                if (
                    i < len(det_union_names)
                    and not actor.union_name.value
                    and det_union_names[i].value
                ):
                    filled[i] = actor.model_copy(update={"union_name": det_union_names[i]})
            actors = filled
            llm_calls += 1

        # Stages 5-9
        for actor in actors:
            row = _build_row(actor, section_ctx, document_name)
            validate_row(row)
            if not row.actor_name:
                logger.debug("Dropping row with no actor name")
                continue
            all_rows.append(row)

    # Record run stats
    if pattern_store is not None:
        from .pattern_store.db import PatternStore

        ps2: PatternStore = pattern_store  # type: ignore[assignment]
        run = ExtractionRun(
            run_id=str(uuid.uuid4()),
            document_name=document_name,
            fingerprint=fingerprint,
            llm_calls=llm_calls,
            rows_extracted=len(all_rows),
            rows_low_confidence=sum(1 for r in all_rows if r.confidence_tier == "low"),
            profile=config.profile_name,
        )
        ps2.record_run(run)

    logger.info("Extracted %d rows from %s", len(all_rows), document_name)
    return all_rows


def _build_row(
    actor: ExtractedActor,
    ctx: SectionContext,
    document_name: str,
) -> ExtractedRow:
    # Stage 5: Section-context join
    rate_raw = str(actor.rate_override_raw.value or ctx.rate_raw)
    if actor.rate_override_raw.value:
        parsed = parse_rate(rate_raw)
        rate_amount = parsed.amount
        rate_unit: RateUnit = parsed.unit
        rate_modifiers = parsed.modifiers
    else:
        rate_amount = ctx.rate_amount
        rate_unit = ctx.rate_unit
        rate_modifiers = ctx.rate_modifiers

    # Stage 6: Normalize name
    # LLM already returns names in FIRST LAST order — applying LAST FIRST flip would double-invert
    effective_convention = (
        ctx.column_convention if actor.actor_name.method == "deterministic" else ""
    )
    actor_name = normalize_name(
        str(actor.actor_name.value or ""),
        column_convention=effective_convention,
    )

    phone = normalize_phone(str(actor.phone.value or ""))
    email = str(actor.email.value or "")
    notes = str(actor.notes.value or "")
    cancelled = bool(actor.cancelled.value)

    source = actor.actor_name.source

    # Determine extraction method
    extraction_method: ExtractionMethod = actor.actor_name.method  # type: ignore[assignment]

    # Stage 7: Confidence
    # Actor-level union detection overrides section context (e.g. "Taft Hartley" in actor row)
    actor_union = str(actor.union_name.value or "")
    union_name: UnionName = actor_union or ctx.union_name  # type: ignore[assignment]

    partial_row = ExtractedRow(
        document_name=document_name,
        call_time=ctx.call_time,
        union_name=union_name,
        actor_name=actor_name,
        role_type=ctx.role_type,
        role=ctx.role,
        rate_raw=rate_raw,
        rate_amount=rate_amount,
        rate_unit=rate_unit,
        rate_modifiers=rate_modifiers,
        phone=phone,
        email=email,
        notes=notes,
        cancelled=cancelled,
        confidence=0.0,
        confidence_tier="low",
        confidence_breakdown={},
        source=source,
        extraction_method=extraction_method,
    )

    score, tier, breakdown = compute_row_confidence(partial_row)
    partial_row.confidence = score
    partial_row.confidence_tier = tier
    partial_row.confidence_breakdown = breakdown

    return partial_row


def _rows_from_outline(
    outline: object,
    document_name: str,
    config: AppConfig,
) -> list[ExtractedRow]:
    """Convert LLM outline result to ExtractedRows."""
    from .models import OutlineResult

    result: OutlineResult = outline  # type: ignore[assignment]
    rows: list[ExtractedRow] = []

    for section in result.sections:
        for actor_dict in getattr(section, "actors", []):
            if isinstance(actor_dict, dict):
                actor_name = normalize_name(str(actor_dict.get("actor_name", "")))
            else:
                actor_name = normalize_name(str(getattr(actor_dict, "actor_name", "")))

            if not actor_name:
                continue

            partial = ExtractedRow(
                document_name=document_name,
                call_time=section.call_time,
                union_name=section.union_name,
                actor_name=actor_name,
                role_type=section.role_type,
                role=section.role,
                rate_raw=section.rate_raw,
                rate_amount=section.rate_amount,
                rate_unit=section.rate_unit,
                rate_modifiers=section.rate_modifiers,
                phone=normalize_phone(
                    str(
                        actor_dict.get("phone", "")
                        if isinstance(actor_dict, dict)
                        else getattr(actor_dict, "phone", "")
                    )
                ),
                email=str(
                    actor_dict.get("email", "")
                    if isinstance(actor_dict, dict)
                    else getattr(actor_dict, "email", "")
                ),
                notes=str(
                    actor_dict.get("notes", "")
                    if isinstance(actor_dict, dict)
                    else getattr(actor_dict, "notes", "")
                ),
                cancelled=bool(
                    actor_dict.get("cancelled", False)
                    if isinstance(actor_dict, dict)
                    else getattr(actor_dict, "cancelled", False)
                ),
                confidence=0.0,
                confidence_tier="low",
                confidence_breakdown={},
                source="llm-outline",
                extraction_method="llm-outline",
            )

            score, tier, breakdown = compute_row_confidence(partial)
            partial.confidence = score
            partial.confidence_tier = tier
            partial.confidence_breakdown = breakdown
            rows.append(partial)

    return rows


def process_directory(
    input_dir: str | Path,
    config: AppConfig,
    llm_extractor: LLMExtractor | None = None,
    pattern_store: object | None = None,
) -> list[ExtractedRow]:
    d = Path(input_dir)
    all_rows: list[ExtractedRow] = []

    input_files = sorted(d.glob("*.pdf")) + sorted(d.glob("*.csv"))
    if not input_files:
        logger.warning("No PDF or CSV files found in %s", d)

    for f in input_files:
        rows = run_pipeline(f, config, llm_extractor, pattern_store)
        all_rows.extend(rows)

    write_clean_csv(all_rows, config.output.clean_csv)
    write_debug_csv(all_rows, config.output.debug_csv)

    return all_rows
