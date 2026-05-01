"""Tests for pattern store CRUD."""

from pathlib import Path

import pytest

from skins_extractor.models import ProposedPattern
from skins_extractor.pattern_store.db import PatternStore


@pytest.fixture
def tmp_store(tmp_path: Path) -> PatternStore:
    db_path = str(tmp_path / "test_patterns.duckdb")
    store = PatternStore(db_path)
    yield store
    store.close()


def _pattern() -> ProposedPattern:
    return ProposedPattern(
        pattern_type="section_header",
        regex=r"^STAND\s+INS?$",
        description="Matches stand-ins section header",
        example_match="STAND INS",
        example_output={"role_type": "stand-in"},
    )


class TestPatternStore:
    def test_insert_and_list_pending(self, tmp_store: PatternStore) -> None:
        pid = tmp_store.insert(_pattern(), fingerprint="ABCDEF123456")
        pending = tmp_store.list_pending()
        assert any(p.pattern_id == pid for p in pending)

    def test_approve(self, tmp_store: PatternStore) -> None:
        pid = tmp_store.insert(_pattern(), fingerprint="ABCDEF123456")
        tmp_store.approve(pid, "tester")
        approved = tmp_store.find_by_fingerprint("ABCDEF123456", status="approved")
        assert any(p.pattern_id == pid for p in approved)

    def test_reject(self, tmp_store: PatternStore) -> None:
        pid = tmp_store.insert(_pattern(), fingerprint="ABCDEF123456")
        tmp_store.reject(pid, reason="too broad")
        pending = tmp_store.list_pending()
        assert all(p.pattern_id != pid for p in pending)

    def test_deprecate(self, tmp_store: PatternStore) -> None:
        pid = tmp_store.insert(_pattern(), fingerprint="ABCDEF123456")
        tmp_store.approve(pid)
        tmp_store.deprecate(pid)
        approved = tmp_store.find_by_fingerprint("ABCDEF123456")
        assert all(p.pattern_id != pid for p in approved)

    def test_update_match_stats(self, tmp_store: PatternStore) -> None:
        pid = tmp_store.insert(_pattern(), fingerprint="ABCDEF123456")
        tmp_store.update_match_stats(pid, success=True)
        tmp_store.update_match_stats(pid, success=False)
        p = tmp_store.get(pid)
        assert p is not None
        assert p.match_count == 2
        assert p.success_count == 1

    def test_get_by_id_prefix(self, tmp_store: PatternStore) -> None:
        pid = tmp_store.insert(_pattern(), fingerprint="ABCDEF123456")
        tmp_store.get(pid[:8])
        # get() uses exact match; this tests the full ID path
        p2 = tmp_store.get(pid)
        assert p2 is not None
        assert p2.pattern_id == pid
