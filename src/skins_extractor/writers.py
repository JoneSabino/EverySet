import csv
import json
import logging
from pathlib import Path

from .models import ExtractedRow

logger = logging.getLogger(__name__)

CLEAN_COLUMNS = [
    "document_name",
    "call_time",
    "union_name",
    "actor_name",
    "role_type",
    "role",
    "rate",
    "phone",
    "confidence",
]

DEBUG_EXTRA_COLUMNS = [
    "email",
    "notes",
    "rate_amount",
    "rate_unit",
    "rate_modifiers",
    "cancelled",
    "confidence_tier",
    "confidence_breakdown",
    "source",
    "extraction_method",
]


def write_clean_csv(rows: list[ExtractedRow], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    visible = [r for r in rows if not r.cancelled]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CLEAN_COLUMNS, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for row in visible:
            writer.writerow(
                {
                    "document_name": row.document_name,
                    "call_time": row.call_time,
                    "union_name": row.union_name,
                    "actor_name": row.actor_name,
                    "role_type": row.role_type,
                    "role": row.role,
                    "rate": row.rate_raw,
                    "phone": row.phone,
                    "confidence": row.confidence,
                }
            )
    logger.info("Wrote %d rows to %s", len(visible), path)


def write_debug_csv(rows: list[ExtractedRow], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    all_columns = CLEAN_COLUMNS + DEBUG_EXTRA_COLUMNS
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_columns, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "document_name": row.document_name,
                    "call_time": row.call_time,
                    "union_name": row.union_name,
                    "actor_name": row.actor_name,
                    "role_type": row.role_type,
                    "role": row.role,
                    "rate": row.rate_raw,
                    "phone": row.phone,
                    "confidence": row.confidence,
                    "email": row.email,
                    "notes": row.notes,
                    "rate_amount": row.rate_amount,
                    "rate_unit": row.rate_unit,
                    "rate_modifiers": json.dumps(row.rate_modifiers),
                    "cancelled": row.cancelled,
                    "confidence_tier": row.confidence_tier,
                    "confidence_breakdown": json.dumps(row.confidence_breakdown),
                    "source": row.source,
                    "extraction_method": row.extraction_method,
                }
            )
    logger.info("Wrote %d rows (debug) to %s", len(rows), path)
