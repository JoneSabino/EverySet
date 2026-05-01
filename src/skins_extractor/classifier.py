"""Classifies RawBlocks into section_header / actor_row / legend / noise."""

from __future__ import annotations

import logging
import re
from typing import Literal

from rapidfuzz import fuzz

from .models import ClassifiedBlock, RateUnit, RawBlock, SectionContext
from .normalizers.enums import ROLE_TYPE_SYNONYMS_FLAT

logger = logging.getLogger(__name__)

_PHONE_RE = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_RATE_RE = re.compile(r"\$\d+|\bvoucher\b|\bday rate\b|\bsee\s+rate\b", re.IGNORECASE)
_CALL_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\s*(AM|PM|am|pm|NOON|noon)?\b")
_LEADING_NUM_RE = re.compile(r"^\d+\s+")

# Section header indicators
_ROLE_KEYWORD_RE = re.compile(
    r"\b(STAND[\s\-]?IN|BACKGROUND|PHOTO[\s\-]?DOUBLE|FEATURED[\s\-]?BACKGROUND|"
    r"SPECIAL[\s\-]?ABILITY|AUDIENCE|FITTING|STAND\s+INS|ND\s+PEDS|MEDICAL|"
    r"PEDESTRIAN|DRIVER|PARKED\s+CARS)\b",
    re.IGNORECASE,
)
_HEADER_ABBREV_RE = re.compile(r"\b(BG|PD|SI|S/I|SpA|ND)\b")
# PDF-style: "ROLE @ TIME to LOCATION"
_AT_TIME_RE = re.compile(r"@\s*\d{1,2}:\d{2}", re.IGNORECASE)
# Column convention indicator
_LAST_FIRST_RE = re.compile(r"\bLAST\s+FIRST\b", re.IGNORECASE)
# Rate with trailing union/SAG label to strip
_RATE_UNION_SUFFIX_RE = re.compile(r"\s+\b(union|non.?union|sag|sag.?aftra|nu)\b.*$", re.IGNORECASE)


def classify_blocks(
    blocks: list[RawBlock],
    stored_patterns: list | None = None,
) -> list[ClassifiedBlock]:
    results: list[ClassifiedBlock] = []
    for block in blocks:
        if not block.text.strip():
            results.append(ClassifiedBlock(block=block, kind="noise", classifier_confidence=1.0))
            continue

        kind, conf = _classify_one(block)
        results.append(ClassifiedBlock(block=block, kind=kind, classifier_confidence=conf))

    return results


def _classify_one(
    block: RawBlock,
) -> tuple[Literal["legend", "section_header", "actor_row", "noise", "unknown"], float]:
    text = block.text.strip()

    # Short empty lines are noise
    if not text or len(text) < 2:
        return "noise", 1.0

    has_phone = bool(_PHONE_RE.search(text))
    has_email = bool(_EMAIL_RE.search(text))

    # Actor rows have phones or emails
    if has_phone or has_email:
        return "actor_row", 0.95

    # Check for cancellation marker XXX
    if re.search(r"\bXXX\b", text):
        return "actor_row", 0.90

    # PDF-style section header: "ROLE @ TIME" pattern (very strong signal)
    if _AT_TIME_RE.search(text) and not has_email:
        return "section_header", 0.95

    # Section headers: role keyword + no phone/email
    if _ROLE_KEYWORD_RE.search(text) and not has_phone and not has_email:
        return "section_header", 0.90

    if _HEADER_ABBREV_RE.search(text) and not has_phone:
        return "section_header", 0.80

    # Call time + role context → section header
    if _CALL_TIME_RE.search(text) and _RATE_RE.search(text):
        return "section_header", 0.85

    # Rate present but no phone/email → section header
    if _RATE_RE.search(text) and not has_phone and not has_email:
        return "section_header", 0.85

    # Section headers with numeric prefix immediately followed by letters (no space):
    # e.g. "2STAND INS", "18BREMEN MALE STAFF", "1BREMEN CAPTAIN IN BRIDGE"
    # This covers multi-word variants that fail the ≤3-token all-caps check.
    if re.match(r"^\d+[A-Z]", text) and not has_phone and not has_email:
        return "section_header", 0.80

    # Single token all-caps → likely a section header or legend
    tokens = text.split()
    if len(tokens) <= 3 and text == text.upper() and len(text) > 2:
        return "section_header", 0.70

    # Fuzzy match against known role keywords
    for keyword in ROLE_TYPE_SYNONYMS_FLAT:
        score = fuzz.token_set_ratio(text.lower(), keyword.lower())
        if score >= 85:
            return "section_header", 0.80

    # Has a numeric prefix (CI# or sequence) → likely actor row
    if _LEADING_NUM_RE.match(text):
        return "actor_row", 0.70

    # Contains name-like pattern + no other signals → unknown
    return "unknown", 0.50


def extract_section_context_from_header(block: RawBlock) -> SectionContext:
    """Parse a section header block into SectionContext."""
    from .normalizers.enums import normalize_role_type, normalize_union
    from .normalizers.rate import parse_rate

    text = block.text.strip()

    role_type, _ = normalize_role_type(text)
    union_name, _ = normalize_union(text)

    call_time = ""
    m = _CALL_TIME_RE.search(text)
    if m:
        call_time = m.group(0).strip()

    rate_raw = ""
    rate_amount = None
    rate_unit: RateUnit = ""
    rate_modifiers: dict = {}
    rm = _RATE_RE.search(text)
    if rm:
        # Find the full rate string around the match — strip trailing "Union"/SAG labels
        rate_raw = text[rm.start() :].split("\n")[0].strip()
        rate_raw = _RATE_UNION_SUFFIX_RE.sub("", rate_raw).strip()
        parsed = parse_rate(rate_raw)
        rate_amount = parsed.amount
        rate_unit = parsed.unit
        rate_modifiers = parsed.modifiers

    # Column convention (e.g. "LAST FIRST" header visible in PDF column headers)
    column_convention = "LAST FIRST" if _LAST_FIRST_RE.search(text) else ""

    # Role: the remaining text after removing known tokens
    role = _extract_role(text, role_type)

    return SectionContext(
        role=role,
        role_type=role_type,
        call_time=call_time,
        union_name=union_name,
        rate_raw=rate_raw,
        rate_amount=rate_amount,
        rate_unit=rate_unit,
        rate_modifiers=rate_modifiers,
        column_convention=column_convention,
    )


def _extract_role(text: str, role_type: str) -> str:
    """Extract freeform role name from section header text."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return ""
    role = lines[0]
    # When call-time was injected as line 0, use the actual header line instead
    if re.match(r"^CALL\s+TIME\s*:", role, re.IGNORECASE) and len(lines) > 1:
        role = lines[1]
    # Strip noise keywords and everything after them ("see rate" before RATE so "see" isn't kept)
    role = re.sub(
        r"\b(see\s+rate|CALL\s+TIME|RATE|UNION|SAG|NON.UNION)\b.*", "", role, flags=re.IGNORECASE
    )
    # Strip embedded rate suffix: "- $224/8 + 250", "= $262/8", or trailing " $250"
    role = re.sub(r"\s*[-–=]\s*\$\d+.*$|\s+\$\d+.*$", "", role)
    # Truncate at @TIME ("STAND INS @ 8:00AM to BREAKFAST 2 CAB DRIVERS..." → "STAND INS")
    role = re.sub(r"\s+@\s*\d{1,2}:\d{2}.*$", "", role)
    # Strip table column-header suffixes ("# Stand Ins Name  Phone # NOTES" → "Stand Ins")
    role = re.sub(r"\b(Name|Phone|NOTES|PHONE)\b.*$", "", role, flags=re.IGNORECASE).strip()
    role = role.lstrip("#").strip(" :-")
    # Strip leading count prefix: "2STAND INS" → "STAND INS", "18BREMEN STAFF" → "BREMEN STAFF"
    role = re.sub(r"^\d+\s*", "", role).strip()
    return role
