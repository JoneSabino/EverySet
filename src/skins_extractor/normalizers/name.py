import re

_LEADING_NUM_RE = re.compile(r"^\d+\s+")
_COMMA_RE = re.compile(r"^([^,]+),\s*(.+)$")


def normalize_name(raw: str, column_convention: str = "") -> str:
    if not raw:
        return ""

    name = raw.strip()

    # Strip leading numeric prefix (CI# or sequence)
    name = _LEADING_NUM_RE.sub("", name).strip()

    # Handle "Last, First" → "First Last"
    m = _COMMA_RE.match(name)
    if m:
        return f"{m.group(2).strip()} {m.group(1).strip()}"

    # If column header says LAST FIRST → flip two-token names
    if column_convention.upper() in ("LAST FIRST", "LAST_FIRST"):
        parts = name.split()
        if len(parts) == 2:
            return f"{parts[1]} {parts[0]}"

    return name
