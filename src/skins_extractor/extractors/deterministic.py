"""Deterministic field extractor using regex and fuzzy matching."""

from __future__ import annotations

import re

from ..models import (
    ClassifiedBlock,
    ExtractedActor,
    FieldExtraction,
    SectionContext,
)
from ..normalizers.enums import ROLE_TYPE_SYNONYMS_FLAT, normalize_union
from ..normalizers.phone import normalize_phone

_PHONE_RE = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_RATE_RE = re.compile(r"(\$\d+(?:\.\d+)?(?:/\d+)?(?:\s*\+\s*\$?\d+)?|\bvoucher\b)", re.IGNORECASE)
_XXX_RE = re.compile(r"\bXXX\b")
_LEADING_NUM_RE = re.compile(r"^\d+\s+")
# Strips leading "HH:MM [NOON|AM|PM]" and optional sequence number from name
_CALL_TIME_PREFIX_RE = re.compile(
    r"^\d{1,2}:\d{2}\s*(?:NOON|noon|AM|PM|am|pm)?\s*\d*\s*", re.IGNORECASE
)
# Strips trailing " union" standalone word (case-insensitive) and anything after a
# vehicle description tag like "89 - Maroon Toyota" or "88 Blue Chevy"
_UNION_SUFFIX_RE = re.compile(r"\s+union\b.*$", re.IGNORECASE)
# Inline union keywords that can appear anywhere in the actor text (e.g. "Taft Hartley")
_UNION_INLINE_RE = re.compile(
    r"\b(Taft\s+Hartley|non.?union|nonunion|SAG.?AFTRA|SAG)\b",
    re.IGNORECASE,
)
_VEHICLE_SUFFIX_RE = re.compile(r"\s+\d{2}\s*[-–]\s*\w.*$")
# Partial email fragment without domain (e.g. "ralph.francisco@")
_PARTIAL_EMAIL_RE = re.compile(r"\s*\S+@\S*")
# Name particles that are legitimately short (don't trigger garbled-name heuristic)
_NAME_PARTICLES = frozenset(
    {"de", "van", "le", "la", "al", "el", "del", "von", "du", "da", "di", "st", "mc"}
)
# Crew role prefixes that should never produce an actor row
_CREW_PREFIX_RE = re.compile(
    r"^(Casting\s+Director|Casting\s+Associate|AD\s+Contact|Assistant\s+Director"
    r"|Production\s+Coordinator|Unit\s+Production\s+Manager)\s*:",
    re.IGNORECASE,
)

# Patterns that indicate the name field is likely garbled — signal LLM to re-examine
_GARBLED_NAME_RE = re.compile(
    r"^\s*:|"  # starts with ":" (garbled time like ":0 0 P M")
    r"\bRATE\s*:|"  # "RATE:" leaked into name
    r"[a-zA-Z0-9]+:(?!\s*//)",  # colon mid-name e.g. "Casting Director:"
    re.IGNORECASE,
)

# Matches when name begins with a known role-type keyword (role prefix leaked into name)
_role_prefix_alts = sorted(ROLE_TYPE_SYNONYMS_FLAT, key=len, reverse=True)
_ROLE_PREFIX_RE = re.compile(
    r"^(?:" + "|".join(re.escape(s) for s in _role_prefix_alts) + r")\b",
    re.IGNORECASE,
)
# Role abbreviations embedded in name text indicate garbled extraction
_ROLE_ABBREV_IN_NAME_RE = re.compile(r"\b(BG|PD|SI|S/I|SpA|ND)\b")


def _has_garbled_fragment(name: str) -> bool:
    """True when name has a standalone 1-3 char lowercase word that isn't a known particle."""
    for word in re.findall(r"\b[a-z]{1,3}\b", name):
        if word not in _NAME_PARTICLES:
            return True
    return False


def _is_initials_noise(name: str) -> bool:
    """True for patterns like 'JS CHECK' — initials + standalone non-name word."""
    return bool(re.match(r"^[A-Z]{1,3}\s+[A-Z]{3,}\s*$", name))


# Actor flag tokens → notes expansions
_FLAGS: dict[str, str] = {
    "TH": "Taft Hartley",
    "SR": "Self Reporting",
    "V": "Voucher",
    "SpA": "Special Ability",
}
_FLAG_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in _FLAGS) + r")\b")


def extract_actors_deterministic(
    actor_blocks: list[ClassifiedBlock],
    section_ctx: SectionContext,
    document_name: str,
    page: int = 1,
) -> list[ExtractedActor]:
    results = []
    for block in actor_blocks:
        actor = _extract_one(block, document_name, page)
        if actor is not None:
            results.append(actor)
    return results


def _extract_one(
    cb: ClassifiedBlock,
    document_name: str,
    page: int,
) -> ExtractedActor | None:
    text = cb.block.text.strip()
    if not text:
        return None

    # Skip crew/staff header lines that are never actor rows
    if _CREW_PREFIX_RE.match(text):
        return None

    source = f"p{cb.block.page}:y{cb.block.y_top:.0f}"

    # Cancellation
    cancelled = bool(_XXX_RE.search(text))

    # Check color-based cancellation (red text)
    if cb.block.fill_color:
        r, g, b = cb.block.fill_color
        if r > 0.7 and g < 0.3 and b < 0.3:
            cancelled = True

    # Phone
    phone_raw = ""
    phone_m = _PHONE_RE.search(text)
    phone_conf = 0.0
    if phone_m:
        phone_raw = normalize_phone(phone_m.group(0))
        phone_conf = 1.0 if phone_raw else 0.5
        text = text[: phone_m.start()] + text[phone_m.end() :]

    # Email
    email_raw = ""
    email_m = _EMAIL_RE.search(text)
    email_conf = 0.0
    if email_m:
        email_raw = email_m.group(0)
        email_conf = 1.0
        text = text[: email_m.start()] + text[email_m.end() :]

    # Rate override
    rate_raw = ""
    rate_conf = 0.0
    rate_m = _RATE_RE.search(text)
    if rate_m:
        rate_raw = rate_m.group(0)
        rate_conf = 1.0
        text = text[: rate_m.start()] + text[rate_m.end() :]

    # Flags → notes
    notes_parts: list[str] = []
    th_flag_detected = False

    def replace_flag(m: re.Match) -> str:
        nonlocal th_flag_detected
        flag = m.group(1) or ""
        notes_parts.append(_FLAGS.get(flag, flag))
        if flag == "TH":
            th_flag_detected = True
        return " "

    text = _FLAG_RE.sub(replace_flag, text)
    notes = "; ".join(notes_parts)

    # Name: what's left after removing all matched fields
    name = text.strip()
    # Strip leading call-time (e.g. "12:00 NOON 1 ", "8:45AM ") before the actual name
    name = _CALL_TIME_PREFIX_RE.sub("", name).strip()
    name = _LEADING_NUM_RE.sub("", name).strip()
    # Strip any partial email fragments (e.g. "ralph.francisco@" left over when a block has
    # two @ signs and only one matches the full email regex)
    name = _PARTIAL_EMAIL_RE.sub("", name).strip()
    # Clean up XXX and stray punctuation
    name = _XXX_RE.sub("", name).strip()
    name = re.sub(r"[,;:]+$", "", name).strip()
    # Detect inline union keywords (e.g. "Taft Hartley") and strip from name
    union_raw = ""
    inline_m = _UNION_INLINE_RE.search(name)
    if inline_m:
        union_raw = inline_m.group(0)
        name = (name[: inline_m.start()] + name[inline_m.end() :]).strip()
    # Strip " union" suffix (e.g. "Rob Odelmo union") — capture as union_raw
    if _UNION_SUFFIX_RE.search(name):
        union_raw = union_raw or "union"
        name = _UNION_SUFFIX_RE.sub("", name).strip()
    # TH flag = Taft-Hartley = non-union, overrides any SAG keyword in same text
    if th_flag_detected:
        union_raw = "non-union"
    union_name_val, union_conf = normalize_union(union_raw) if union_raw else ("", 0.0)
    # Strip trailing vehicle descriptions (e.g. "89 - Maroon Toyota Pickup")
    name = _VEHICLE_SUFFIX_RE.sub("", name).strip()
    # Strip trailing stray ")" introduced by PDF column misalignment
    name = re.sub(r"\s*\)\s*$", "", name).strip()

    # Skip rows where no name is recoverable
    if not name and not phone_raw:
        return None

    # Skip low-signal rows: only classified via leading-num heuristic and no phone/email.
    # These are usually ZIP codes, location addresses, or notes — not actors.
    if cb.classifier_confidence <= 0.70 and not phone_raw and not email_raw:
        return None

    if not name:
        name_conf = 0.0
    elif (
        _GARBLED_NAME_RE.search(name)
        or _has_garbled_fragment(name)
        or _is_initials_noise(name)
        or bool(_ROLE_PREFIX_RE.match(name))
        or bool(_ROLE_ABBREV_IN_NAME_RE.search(name))
    ):
        name_conf = 0.20  # signal LLM fallback to re-examine this section
    else:
        name_conf = 0.95

    return ExtractedActor(
        actor_name=FieldExtraction(
            value=name, method="deterministic", confidence=name_conf, source=source
        ),
        phone=FieldExtraction(
            value=phone_raw, method="deterministic", confidence=phone_conf, source=source
        ),
        email=FieldExtraction(
            value=email_raw, method="deterministic", confidence=email_conf, source=source
        ),
        notes=FieldExtraction(
            value=notes, method="deterministic", confidence=0.9 if notes else 0.0, source=source
        ),
        rate_override_raw=FieldExtraction(
            value=rate_raw, method="deterministic", confidence=rate_conf, source=source
        ),
        cancelled=FieldExtraction(
            value=cancelled, method="deterministic", confidence=0.95, source=source
        ),
        union_name=FieldExtraction(
            value=union_name_val, method="deterministic", confidence=union_conf, source=source
        ),
    )
