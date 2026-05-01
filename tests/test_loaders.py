"""Tests for document loaders."""

from pathlib import Path

from skins_extractor.loaders.csv import CSVLoader
from skins_extractor.models import RawBlock


class TestCSVLoader:
    def test_loads_skins3(self, sample_csv_path: Path) -> None:
        loader = CSVLoader()
        blocks = loader.load(sample_csv_path)
        assert len(blocks) > 0
        assert all(isinstance(b, RawBlock) for b in blocks)

    def test_contains_actor_names(self, sample_csv_path: Path) -> None:
        loader = CSVLoader()
        blocks = loader.load(sample_csv_path)
        texts = " ".join(b.text for b in blocks)
        assert "Ralph Francisco" in texts
        assert "Janice Torno" in texts

    def test_skips_empty_rows(self, sample_csv_path: Path) -> None:
        loader = CSVLoader()
        blocks = loader.load(sample_csv_path)
        # No block should be empty
        assert all(b.text.strip() for b in blocks)
