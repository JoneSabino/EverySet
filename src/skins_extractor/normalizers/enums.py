from __future__ import annotations

from rapidfuzz import fuzz, process

from ..models import RoleType, UnionName

ROLE_TYPE_SYNONYMS: dict[str, list[str]] = {
    "stand-in": ["stand in", "stand-in", "standin", "stand ins", "s/i", "si", "stand ins"],
    "background": [
        "background",
        "bg",
        "nd peds",
        "nd",
        "atmosphere",
        "extras",
        "non-descript",
        "peds",
        "pedestrians",
        "guests",
        "medical",
        "medical employees",
        "male staff",
        "female staff",
        "staff",
        "employees",
        "parked cars",
        "cars",
    ],
    "photo double": ["photo double", "pd", "p/d", "photo doubles"],
    "featured background": ["featured background", "featured bg", "featured"],
    "special ability": ["special ability", "spa", "sp ab", "special abilities"],
    "audience": ["audience", "audience members"],
}

UNION_SYNONYMS: dict[str, list[str]] = {
    "union": ["union", "sag", "sag-aftra", "sag aftra", "sag/aftra"],
    "sag-aftra": ["sag-aftra", "sag aftra", "sag/aftra"],
    "non-union": ["non-union", "non union", "nu", "non-u", "nonunion", "taft hartley", "th"],
}

# Flat lists for fuzzy matching
ROLE_TYPE_SYNONYMS_FLAT: list[str] = [
    s for synonyms in ROLE_TYPE_SYNONYMS.values() for s in synonyms
]
UNION_SYNONYMS_FLAT: list[str] = [s for synonyms in UNION_SYNONYMS.values() for s in synonyms]

_ROLE_TYPE_ALL: list[tuple[str, str]] = [
    (synonym, canonical)
    for canonical, synonyms in ROLE_TYPE_SYNONYMS.items()
    for synonym in synonyms
]
_UNION_ALL: list[tuple[str, str]] = [
    (synonym, canonical) for canonical, synonyms in UNION_SYNONYMS.items() for synonym in synonyms
]


def normalize_role_type(text: str) -> tuple[RoleType, float]:
    return _fuzzy_match(text.lower(), _ROLE_TYPE_ALL, default="")  # type: ignore[return-value]


def normalize_union(text: str) -> tuple[UnionName, float]:
    return _fuzzy_match(text.lower(), _UNION_ALL, default="")  # type: ignore[return-value]


def _fuzzy_match(
    text: str,
    candidates: list[tuple[str, str]],
    default: str,
) -> tuple[str, float]:
    if not candidates or not text.strip():
        return default, 0.0

    synonyms = [c[0] for c in candidates]
    # Get all results so we can break ties by synonym specificity (longer = more specific)
    all_results = process.extract(text, synonyms, scorer=fuzz.token_set_ratio, limit=len(synonyms))
    if not all_results:
        return default, 0.0

    top_score = all_results[0][1]
    normalized_score = top_score / 100.0

    if normalized_score < 0.70:
        return default, 0.0

    # Among matches within 2 points of the top score, prefer by exact ratio first
    # (breaks "background" vs "featured background" tie), then by synonym length
    top_results = [r for r in all_results if r[1] >= top_score - 2]
    best_synonym, _, idx = max(
        top_results,
        key=lambda r: (fuzz.ratio(text, r[0]), len(r[0])),
    )

    canonical = candidates[idx][1]

    if normalized_score >= 0.95:
        return canonical, 0.95  # type: ignore[return-value]
    elif normalized_score >= 0.85:
        return canonical, 0.85  # type: ignore[return-value]
    else:
        return canonical, 0.70  # type: ignore[return-value]
