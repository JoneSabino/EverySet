"""Column-aware CSV loader for Skins 3 roster format."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from ..models import RawBlock

# Header column names that indicate the roster column layout
_HEADER_PATTERNS = {
    "ci": re.compile(r"CI#?", re.IGNORECASE),
    "name": re.compile(r"^name$", re.IGNORECASE),
    "phone": re.compile(r"phone", re.IGNORECASE),
    "email": re.compile(r"email", re.IGNORECASE),
    "union": re.compile(r"union", re.IGNORECASE),
}


class CSVLoader:
    def load(self, path: Path) -> list[RawBlock]:
        rows = self._read_rows(path)
        return self._parse_rows(rows)

    def _read_rows(self, path: Path) -> list[list[str]]:
        rows = []
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            for row in reader:
                rows.append(row)
        return rows

    def _parse_rows(self, rows: list[list[str]]) -> list[RawBlock]:
        """
        Detect the column layout from header rows, then emit structured blocks.
        Falls back to simple text joining if no header found.
        """
        col_map = self._detect_columns(rows)

        if col_map:
            return self._parse_structured(rows, col_map)
        else:
            return self._parse_unstructured(rows)

    def _detect_columns(self, rows: list[list[str]]) -> dict[str, int] | None:
        """Find the header row and return column index map."""
        for i, row in enumerate(rows):
            mapping: dict[str, int] = {}
            for j, cell in enumerate(row):
                cell = cell.strip()
                if _HEADER_PATTERNS["name"].match(cell):
                    mapping["name"] = j
                elif _HEADER_PATTERNS["phone"].search(cell):
                    mapping["phone"] = j
                elif _HEADER_PATTERNS["email"].search(cell):
                    mapping["email"] = j
                elif _HEADER_PATTERNS["ci"].search(cell):
                    mapping["ci"] = j
                elif _HEADER_PATTERNS["union"].search(cell):
                    mapping["union"] = j

            if "name" in mapping and "phone" in mapping:
                return mapping

        return None

    def _parse_structured(self, rows: list[list[str]], col_map: dict[str, int]) -> list[RawBlock]:
        """Parse using detected column positions."""
        name_col = col_map.get("name")
        phone_col = col_map.get("phone")
        email_col = col_map.get("email")
        ci_col = col_map.get("ci")

        blocks: list[RawBlock] = []

        for i, row in enumerate(rows):
            if not any(cell.strip() for cell in row):
                continue

            # Check if this looks like a section header (has role keyword but no name/phone)
            non_empty = [cell.strip() for cell in row if cell.strip()]
            first_non_empty = non_empty[0] if non_empty else ""

            # Section header: a row with role-type keyword in first col, no phone data
            is_header_row = self._is_section_header_row(row, phone_col, name_col)
            is_meta_row = self._is_meta_row(row, name_col)

            if is_meta_row:
                blocks.append(
                    RawBlock(
                        text=first_non_empty,
                        page=1,
                        y_top=float(i),
                        y_bottom=float(i + 1),
                        x_left=0.0,
                        x_right=800.0,
                    )
                )
                continue

            if is_header_row:
                # Reconstruct section text from the row
                section_text = self._section_text_from_row(row, i)
                if section_text:
                    blocks.append(
                        RawBlock(
                            text=section_text,
                            page=1,
                            y_top=float(i),
                            y_bottom=float(i + 1),
                            x_left=0.0,
                            x_right=800.0,
                        )
                    )
                continue

            # Actor row — extract fields by column
            name = self._get_cell(row, name_col) if name_col is not None else ""
            phone = self._get_cell(row, phone_col) if phone_col is not None else ""
            email = self._get_cell(row, email_col) if email_col is not None else ""
            ci = self._get_cell(row, ci_col) if ci_col is not None else ""

            # Union column: include if non-numeric (e.g. "Taft Hartley", "SAG") so
            # normalize_union can pick it up; skip raw union card numbers
            union_col = col_map.get("union")
            union_val = self._get_cell(row, union_col) if union_col is not None else ""
            if union_val and union_val.isdigit():
                union_val = "union"  # SAG card number → member

            if not name and not phone:
                continue

            # Build a structured actor text that our extractor can parse
            # Format: "CI NAME PHONE EMAIL [UNION_STATUS]"
            parts = []
            if ci:
                parts.append(ci)
            if name:
                parts.append(name)
            if phone:
                parts.append(phone)
            if email:
                parts.append(email)
            if union_val:
                parts.append(union_val)

            # Also include any extra cells (e.g., special rate notes)
            extra_cells = [
                cell.strip()
                for j, cell in enumerate(row)
                if cell.strip()
                and j not in (name_col, phone_col, email_col, ci_col)
                and col_map.get("union") != j
            ]
            # Prepend any special rate/note info that might be in col 0
            if extra_cells:
                parts = extra_cells[:1] + parts  # leading special info

            actor_text = " ".join(p for p in parts if p)

            if actor_text:
                blocks.append(
                    RawBlock(
                        text=actor_text,
                        page=1,
                        y_top=float(i),
                        y_bottom=float(i + 1),
                        x_left=0.0,
                        x_right=800.0,
                    )
                )

        return blocks

    def _get_cell(self, row: list[str], col: int | None) -> str:
        if col is None or col >= len(row):
            return ""
        return row[col].strip()

    def _is_section_header_row(
        self, row: list[str], phone_col: int | None, name_col: int | None
    ) -> bool:
        """A row is a section header if it has role-type text but no phone/name data."""
        phone_val = self._get_cell(row, phone_col)
        name_val = self._get_cell(row, name_col)

        if phone_val or name_val:
            return False

        non_empty = [c.strip() for c in row if c.strip()]
        if not non_empty:
            return False

        combined = " ".join(non_empty)
        import re

        role_keywords = re.compile(
            r"\b(STAND.?IN|BACKGROUND|PHOTO.?DOUBLE|FEATURED|SPECIAL.?ABILITY|"
            r"AUDIENCE|FITTING|BG|PD|SI)\b",
            re.IGNORECASE,
        )
        return bool(role_keywords.search(combined))

    def _is_meta_row(self, row: list[str], name_col: int | None) -> bool:
        """Detect metadata rows like 'WORKING THURSDAY 4/16/2026' or 'Casting Project'."""
        non_empty = [c.strip() for c in row if c.strip()]
        if len(non_empty) == 1:
            text = non_empty[0]
            if len(text) > 5 and not any(ch.isdigit() and "-" in text for ch in text):
                return True
        return False

    def _section_text_from_row(self, row: list[str], idx: int) -> str:
        non_empty = [c.strip() for c in row if c.strip()]
        return " ".join(non_empty)

    def _parse_unstructured(self, rows: list[list[str]]) -> list[RawBlock]:
        """Fallback: join all non-empty cells."""
        blocks: list[RawBlock] = []
        for i, row in enumerate(rows):
            text = " ".join(cell.strip() for cell in row if cell.strip())
            if text:
                blocks.append(
                    RawBlock(
                        text=text,
                        page=1,
                        y_top=float(i),
                        y_bottom=float(i + 1),
                        x_left=0.0,
                        x_right=800.0,
                    )
                )
        return blocks
