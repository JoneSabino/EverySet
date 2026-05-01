import logging
import re

logger = logging.getLogger(__name__)

_DIGITS_RE = re.compile(r"\D")


def normalize_phone(raw: str) -> str:
    if not raw:
        return ""

    digits = _DIGITS_RE.sub("", raw)

    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]

    if len(digits) != 10:
        logger.warning("Invalid phone number (not 10 digits after cleanup): %r", raw)
        return ""

    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
