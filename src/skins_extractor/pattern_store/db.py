"""DuckDB-backed pattern store."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import duckdb

from ..models import ExtractionRun, ProposedPattern, StoredPattern

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _coerce_datetime(val: object) -> str | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.isoformat()
    return str(val)


class PatternStore:
    def __init__(self, db_path: str = "data/patterns.duckdb") -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        schema_sql = _SCHEMA_PATH.read_text()
        # DuckDB doesn't support multiple statements in one execute — split them
        for stmt in schema_sql.split(";"):
            stmt = stmt.strip()
            if stmt:
                self._conn.execute(stmt)

    def insert(
        self,
        pattern: ProposedPattern,
        fingerprint: str,
        status: Literal["pending_review", "approved"] = "pending_review",
        created_by: str = "llm",
    ) -> str:
        pid = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """
            INSERT INTO extraction_patterns
              (pattern_id, pattern_type, format_fingerprint, regex, description,
               example_match, example_output, created_by, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                pid,
                pattern.pattern_type,
                fingerprint,
                pattern.regex,
                pattern.description,
                pattern.example_match,
                json.dumps(pattern.example_output),
                created_by,
                status,
                now,
            ],
        )
        logger.info("Inserted pattern %s (%s) status=%s", pid[:8], pattern.pattern_type, status)
        return pid

    def find_by_fingerprint(
        self,
        fingerprint: str,
        status: str = "approved",
    ) -> list[StoredPattern]:
        rows = self._conn.execute(
            "SELECT * FROM extraction_patterns WHERE format_fingerprint = ? AND status = ?",
            [fingerprint, status],
        ).fetchall()

        columns = [col[0] for col in self._conn.description or []]
        return [self._to_pattern(columns, row) for row in rows]

    def update_match_stats(self, pattern_id: str, success: bool) -> None:
        now = datetime.now(UTC).isoformat()
        increment = 1 if success else 0
        self._conn.execute(
            """
            UPDATE extraction_patterns
            SET match_count = match_count + 1,
                success_count = success_count + ?,
                last_matched_at = ?
            WHERE pattern_id = ?
            """,
            [increment, now, pattern_id],
        )

    def _to_pattern(self, columns: list[str], row: tuple) -> StoredPattern:
        d = dict(zip(columns, row))
        if isinstance(d.get("example_output"), str):
            d["example_output"] = json.loads(d["example_output"])
        d["created_at"] = _coerce_datetime(d.get("created_at")) or ""
        d["approved_at"] = _coerce_datetime(d.get("approved_at"))
        d["last_matched_at"] = _coerce_datetime(d.get("last_matched_at"))
        return StoredPattern(**d)

    def list_pending(self) -> list[StoredPattern]:
        rows = self._conn.execute(
            "SELECT * FROM extraction_patterns"
            " WHERE status = 'pending_review' ORDER BY created_at DESC"
        ).fetchall()
        columns = [col[0] for col in self._conn.description or []]
        return [self._to_pattern(columns, row) for row in rows]

    def list_all(self, status: str | None = None) -> list[StoredPattern]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM extraction_patterns WHERE status = ? ORDER BY created_at DESC",
                [status],
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM extraction_patterns ORDER BY status, created_at DESC"
            ).fetchall()
        columns = [col[0] for col in self._conn.description or []]
        return [self._to_pattern(columns, row) for row in rows]

    def get(self, pattern_id: str) -> StoredPattern | None:
        rows = self._conn.execute(
            "SELECT * FROM extraction_patterns WHERE pattern_id = ?", [pattern_id]
        ).fetchall()
        if not rows:
            return None
        columns = [col[0] for col in self._conn.description or []]
        return self._to_pattern(columns, rows[0])

    def approve(self, pattern_id: str, approver: str = "human") -> None:
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "UPDATE extraction_patterns"
            " SET status = 'approved', approved_by = ?, approved_at = ? WHERE pattern_id = ?",
            [approver, now, pattern_id],
        )

    def reject(self, pattern_id: str, reason: str = "") -> None:
        self._conn.execute(
            "UPDATE extraction_patterns"
            " SET status = 'rejected', description = description || ? WHERE pattern_id = ?",
            [f" [REJECTED: {reason}]", pattern_id],
        )

    def deprecate(self, pattern_id: str) -> None:
        self._conn.execute(
            "UPDATE extraction_patterns SET status = 'deprecated' WHERE pattern_id = ?",
            [pattern_id],
        )

    def record_run(self, run: ExtractionRun) -> None:
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """
            INSERT INTO extraction_runs
              (run_id, document_name, fingerprint, patterns_used, llm_calls,
               rows_extracted, rows_low_confidence, profile, ran_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                run.run_id,
                run.document_name,
                run.fingerprint,
                json.dumps(run.patterns_used),
                run.llm_calls,
                run.rows_extracted,
                run.rows_low_confidence,
                run.profile,
                now,
            ],
        )

    def close(self) -> None:
        self._conn.close()
