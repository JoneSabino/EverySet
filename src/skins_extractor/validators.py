import logging
import re

from .models import ExtractedRow

logger = logging.getLogger(__name__)

_PHONE_PATTERN = re.compile(r"^\d{3}-\d{3}-\d{4}$")

VALID_ROLE_TYPES = {
    "stand-in",
    "background",
    "photo double",
    "featured background",
    "special ability",
    "audience",
    "",
}
VALID_UNION_NAMES = {"union", "sag-aftra", "non-union", ""}
VALID_RATE_UNITS = {"day_8h", "hourly", "voucher", "flat", ""}


def validate_row(row: ExtractedRow) -> list[str]:
    errors: list[str] = []

    if row.phone and not _PHONE_PATTERN.match(row.phone):
        errors.append(f"phone format invalid: {row.phone!r}")

    if row.rate_amount is not None and not isinstance(row.rate_amount, (int, float)):
        errors.append(f"rate_amount must be numeric: {row.rate_amount!r}")

    if row.role_type not in VALID_ROLE_TYPES:
        errors.append(f"role_type not in enum: {row.role_type!r}")

    if row.union_name not in VALID_UNION_NAMES:
        errors.append(f"union_name not in enum: {row.union_name!r}")

    if not (0.0 <= row.confidence <= 1.0):
        errors.append(f"confidence out of range: {row.confidence}")

    if not row.actor_name:
        errors.append("actor_name is empty — row should be dropped")

    if not isinstance(row.cancelled, bool):
        errors.append(f"cancelled must be bool: {row.cancelled!r}")

    if errors:
        logger.warning("Validation errors for %r: %s", row.actor_name, "; ".join(errors))

    return errors
