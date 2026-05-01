from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import RateUnit

_DOLLAR_RE = re.compile(r"\$(\d+(?:\.\d+)?)")
_NO_DOLLAR_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)\s*/\s*\d+")
_PER_HOURS_RE = re.compile(r"/(\d+)")
_HOURLY_RE = re.compile(r"/hr|/hour|per\s+hour", re.IGNORECASE)
_VOUCHER_RE = re.compile(r"\bvoucher\b", re.IGNORECASE)
_FLAT_RE = re.compile(r"\bflat\b|\bguarantee\b", re.IGNORECASE)
_MIN_HOURS_RE = re.compile(r"min(?:imum)?\s+(\d+)\s+hr", re.IGNORECASE)

# Named extras that appear after "+" in composite rates
_EXTRA_RE = re.compile(
    r"\+\s*\$?(\d+(?:\.\d+)?)\s*(?:(bump|kit|fitting|wardrobe|mileage|meal|box|rental))?",
    re.IGNORECASE,
)

_DAY_UNITS: dict[str, RateUnit] = {"8": "day_8h", "10": "day_10h", "12": "day_12h"}


@dataclass
class ParsedRate:
    amount: float | None = None
    unit: RateUnit = ""
    modifiers: dict = field(default_factory=dict)


def parse_rate(raw: str) -> ParsedRate:
    if not raw:
        return ParsedRate()

    result = ParsedRate()
    text = raw.strip()

    # Voucher flag
    if _VOUCHER_RE.search(text):
        result.modifiers["voucher"] = True

    # Base amount: first explicit $X figure
    dollar_m = _DOLLAR_RE.search(text)
    if dollar_m:
        result.amount = float(dollar_m.group(1))
    else:
        # Fallback: bare number before /N (e.g. "150/8")
        no_dollar_m = _NO_DOLLAR_RE.search(text)
        if no_dollar_m:
            result.amount = float(no_dollar_m.group(1))

    # Unit detection
    if _HOURLY_RE.search(text):
        result.unit = "hourly"
    elif result.modifiers.get("voucher") and result.amount is None:
        result.unit = "voucher"
    elif per_m := _PER_HOURS_RE.search(text):
        hours = per_m.group(1)
        result.unit = _DAY_UNITS.get(hours, "flat")
    elif _FLAT_RE.search(text):
        result.unit = "flat"
    elif result.amount is not None:
        result.unit = "flat"

    if result.modifiers.get("voucher") and result.unit == "":
        result.unit = "voucher"

    # Minimum hours
    if min_m := _MIN_HOURS_RE.search(text):
        result.modifiers["min_hours"] = int(min_m.group(1))

    # All extras after "+" — collect as list if multiple, scalar if one (backward compat)
    extras: list[dict] = []
    for m in _EXTRA_RE.finditer(text):
        amount = float(m.group(1))
        label = (m.group(2) or "bump").lower()
        extras.append({"amount": amount, "label": label})

    if len(extras) == 1 and extras[0]["label"] == "bump":
        result.modifiers["bump"] = extras[0]["amount"]
    elif extras:
        result.modifiers["extras"] = extras

    return result
