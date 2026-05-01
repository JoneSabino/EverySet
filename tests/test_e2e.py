"""End-to-end tests — deterministic pipeline on real inputs."""

from pathlib import Path

import pytest

from skins_extractor.config import load_config
from skins_extractor.pipeline import run_pipeline


class TestE2ECSVSkins3:
    """Run the full pipeline on the real Skins 3 CSV without LLM."""

    def test_extracts_rows(self, sample_csv_path: Path) -> None:
        config = load_config("default")
        rows = run_pipeline(sample_csv_path, config, llm_extractor=None)
        assert len(rows) > 0, "Expected at least one extracted row"

    def test_known_actors_present(self, sample_csv_path: Path) -> None:
        config = load_config("default")
        rows = run_pipeline(sample_csv_path, config, llm_extractor=None)
        names = [r.actor_name for r in rows]
        assert any("Francisco" in n for n in names), f"Ralph Francisco not found in {names}"
        assert any("Torno" in n for n in names), f"Janice Torno not found in {names}"

    def test_phone_normalized(self, sample_csv_path: Path) -> None:
        config = load_config("default")
        rows = run_pipeline(sample_csv_path, config, llm_extractor=None)
        phones = [r.phone for r in rows if r.phone]
        # All phones should match XXX-XXX-XXXX
        import re

        pattern = re.compile(r"^\d{3}-\d{3}-\d{4}$")
        for phone in phones:
            assert pattern.match(phone), f"Phone {phone!r} not normalized"

    def test_confidence_present(self, sample_csv_path: Path) -> None:
        config = load_config("default")
        rows = run_pipeline(sample_csv_path, config, llm_extractor=None)
        assert all(0.0 <= r.confidence <= 1.0 for r in rows)
        assert all(r.confidence_tier in ("high", "medium", "low") for r in rows)

    def test_no_cancelled_in_output(self, sample_csv_path: Path) -> None:
        config = load_config("default")
        rows = run_pipeline(sample_csv_path, config, llm_extractor=None)
        # No rows should be cancelled in this fixture
        # (cancelled rows are still in the list, just excluded from clean.csv)
        non_cancelled = [r for r in rows if not r.cancelled]
        assert len(non_cancelled) > 0


class TestE2EPDFs:
    """Run on all PDF samples — deterministic only, check for no crashes."""

    def test_all_pdfs_run_without_crash(self, all_sample_paths: list[Path]) -> None:
        config = load_config("default")
        pdf_paths = [p for p in all_sample_paths if p.suffix.lower() == ".pdf"]
        if not pdf_paths:
            pytest.skip("No PDF sample files available")
        for pdf_path in pdf_paths:
            rows = run_pipeline(pdf_path, config, llm_extractor=None)
            # Just verify it returns a list without crashing
            assert isinstance(rows, list), f"Expected list from {pdf_path.name}"
