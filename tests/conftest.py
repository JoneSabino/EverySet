"""Shared fixtures for the test suite."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
PDFS_DIR = FIXTURES_DIR / "pdfs"
EXPECTED_DIR = FIXTURES_DIR / "expected"
SYNTHETIC_DIR = FIXTURES_DIR / "synthetic"


@pytest.fixture
def sample_csv_path() -> Path:
    """Path to the real Skins 3 CSV for integration tests."""
    p = (
        Path(__file__).parent.parent.parent
        / "ai-take-home-assessment"
        / "skins-report-samples"
        / "RECREATED Skins 3.csv"
    )
    if not p.exists():
        pytest.skip(f"Sample CSV not found at {p}")
    return p


@pytest.fixture
def all_sample_paths() -> list[Path]:
    """All 5 sample input files."""
    base = Path(__file__).parent.parent.parent / "ai-take-home-assessment" / "skins-report-samples"
    files = sorted(base.glob("*.pdf")) + sorted(base.glob("*.csv"))
    return files
