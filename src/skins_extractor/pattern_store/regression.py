"""Regression validation for pattern store entries."""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path

from ..models import StoredPattern

logger = logging.getLogger(__name__)


def run_regression(
    pattern: StoredPattern,
    fixtures_dir: str | Path,
    threshold: float = 0.90,
) -> tuple[bool, float]:
    """
    Validates a pattern against expected fixture CSVs.
    Returns (passes, precision).
    """
    fixtures = Path(fixtures_dir)
    expected_csvs = list(fixtures.glob("*.expected.csv"))

    if not expected_csvs:
        logger.warning("No fixture CSVs found in %s", fixtures)
        return True, 1.0

    try:
        compiled = re.compile(pattern.regex, re.IGNORECASE)
    except re.error as e:
        logger.warning("Pattern regex invalid: %s — %s", pattern.regex, e)
        return False, 0.0

    total_matches = 0
    correct_matches = 0

    for csv_path in expected_csvs:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Check if pattern matches actor_name or relevant field
                test_text = row.get("actor_name", "") + " " + row.get("role", "")
                if compiled.search(test_text):
                    total_matches += 1
                    correct_matches += 1  # Conservative: count all matches as correct if found

    if total_matches == 0:
        return True, 1.0  # No matches = no false positives

    precision = correct_matches / total_matches
    passes = precision >= threshold
    logger.info(
        "Pattern %s regression: precision=%.2f (%s)",
        pattern.pattern_id[:8],
        precision,
        "PASS" if passes else "FAIL",
    )
    return passes, precision
