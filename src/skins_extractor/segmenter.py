"""Groups RawBlocks into sections based on classification results."""

from __future__ import annotations

import re

from .models import ClassifiedBlock, RawBlock

# Section headers that are dispatch/contact metadata, not casting sections —
# any actor_rows beneath them are contact rows, not actors.
_CONTACT_SECTION_RE = re.compile(
    r"\b(CALL\s+or\s+TEXT\s+FOR|MISSING\s+BG|CONTACT\s+INFO|CASTING\s+OFFICE)\b",
    re.IGNORECASE,
)
# Standalone "CALL TIME: HH:MM" blocks that precede a section header
_CALL_TIME_BLOCK_RE = re.compile(r"CALL\s+TIME\s*:\s*\d{1,2}:\d{2}", re.IGNORECASE)
_AT_TIME_RE = re.compile(r"@\s*\d{1,2}:\d{2}", re.IGNORECASE)


def segment_blocks(
    classified: list[ClassifiedBlock],
) -> list[tuple[ClassifiedBlock, list[ClassifiedBlock], list[ClassifiedBlock]]]:
    """
    Returns list of (section_header_block, [actor_row_blocks], [unknown_blocks]).
    Unknown blocks within a section are collected so the LLM fallback can include
    data that the classifier couldn't confidently label (e.g. phone numbers in
    separate PDF columns).

    When a standalone "CALL TIME: HH:MM" unknown block appears before a section_header,
    the call_time is injected into that header's text so extract_section_context_from_header
    can pick it up.
    """
    sections: list[tuple[ClassifiedBlock, list[ClassifiedBlock], list[ClassifiedBlock]]] = []
    current_header: ClassifiedBlock | None = None
    current_rows: list[ClassifiedBlock] = []
    current_unknowns: list[ClassifiedBlock] = []
    pending_call_time: str = ""

    skip_section = False  # True when the current section is contact/dispatch metadata

    for cb in classified:
        if cb.kind == "section_header":
            if current_header is not None or current_rows:
                if current_header is not None and not skip_section:
                    sections.append((current_header, current_rows, current_unknowns))

            # Inject pending call_time into header text if header has no @TIME pattern
            header_block = cb.block
            if pending_call_time and not _AT_TIME_RE.search(header_block.text):
                merged_text = pending_call_time + "\n" + header_block.text
                header_block = RawBlock(
                    text=merged_text,
                    page=cb.block.page,
                    y_top=cb.block.y_top,
                    y_bottom=cb.block.y_bottom,
                    x_left=cb.block.x_left,
                    x_right=cb.block.x_right,
                )
                cb = ClassifiedBlock(
                    block=header_block,
                    kind="section_header",
                    classifier_confidence=cb.classifier_confidence,
                )
            pending_call_time = ""

            current_header = cb
            current_rows = []
            current_unknowns = []
            skip_section = bool(_CONTACT_SECTION_RE.search(cb.block.text))
        elif cb.kind == "actor_row" and not skip_section:
            current_rows.append(cb)
        elif cb.kind == "unknown":
            if _CALL_TIME_BLOCK_RE.search(cb.block.text):
                pending_call_time = cb.block.text.strip()
            elif not skip_section:
                current_unknowns.append(cb)
        # noise/legend: skip

    if current_header is not None and not skip_section:
        sections.append((current_header, current_rows, current_unknowns))

    return sections
