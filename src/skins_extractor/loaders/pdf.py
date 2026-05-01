from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..models import RawBlock

logger = logging.getLogger(__name__)


class PDFLoader:
    def __init__(self, ocr_min_chars: int = 50) -> None:
        self.ocr_min_chars = ocr_min_chars

    def load(self, path: Path) -> list[RawBlock]:
        blocks = self._load_pdfplumber(path)
        total_chars = sum(len(b.text) for b in blocks)

        if total_chars < self.ocr_min_chars:
            logger.warning(
                "pdfplumber returned little text (%d chars), trying pymupdf", total_chars
            )
            blocks = self._load_pymupdf(path)
            total_chars = sum(len(b.text) for b in blocks)

        if total_chars < self.ocr_min_chars:
            logger.warning("pymupdf also returned little text — flagging for vision OCR")
            for b in blocks:
                b.text = b.text + "\n[NEEDS_VISION_OCR]"

        return blocks

    def _load_pdfplumber(self, path: Path) -> list[RawBlock]:
        import pdfplumber

        blocks: list[RawBlock] = []
        with pdfplumber.open(str(path)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=False)
                if not words:
                    # Fallback: get chars-based text
                    text = page.extract_text() or ""
                    if text.strip():
                        blocks.append(
                            RawBlock(
                                text=text.strip(),
                                page=page_num,
                                y_top=0.0,
                                y_bottom=float(page.height),
                                x_left=0.0,
                                x_right=float(page.width),
                            )
                        )
                    continue

                page_width = float(page.width)
                page_blocks = self._words_to_blocks(words, page_num, page_width)
                blocks.extend(page_blocks)

        return blocks

    def _words_to_blocks(
        self,
        words: list[dict[str, Any]],
        page_num: int,
        page_width: float,
    ) -> list[RawBlock]:
        """
        Group words into logical lines by y-proximity, then segment into blocks.

        Multi-column handling: PDFs often have left (actor roster), middle, and right (rates)
        columns. We detect the column boundary and process each column's lines independently,
        then merge back in y-order for the classifier.
        """
        # Group words by y-coordinate (within 3pt tolerance)
        by_y: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for w in words:
            y_key = round(w["top"])
            # Snap nearby y-values together
            snapped = self._snap_y(y_key, by_y.keys())
            by_y[snapped].append(w)

        # Detect column split point: look for a gap in x-distribution
        all_x0 = [w["x0"] for w in words]
        col_split = self._detect_column_split(all_x0, page_width)

        # Build lines from each column separately
        left_lines: list[
            tuple[int, str, float, float, float, float]
        ] = []  # (y, text, y_top, y_bot, x_l, x_r)
        right_lines: list[tuple[int, str, float, float, float, float]] = []

        for y, line_words in sorted(by_y.items()):
            sorted_words = sorted(line_words, key=lambda w: w["x0"])

            left_ws = [w for w in sorted_words if w["x0"] < col_split]
            right_ws = [w for w in sorted_words if w["x0"] >= col_split]

            if left_ws:
                text = " ".join(w["text"] for w in left_ws)
                y_top = min(w["top"] for w in left_ws)
                y_bot = max(w["bottom"] for w in left_ws)
                x_l = min(w["x0"] for w in left_ws)
                x_r = max(w["x1"] for w in left_ws)
                left_lines.append((y, text, y_top, y_bot, x_l, x_r))

            if right_ws:
                text = " ".join(w["text"] for w in right_ws)
                y_top = min(w["top"] for w in right_ws)
                y_bot = max(w["bottom"] for w in right_ws)
                x_l = min(w["x0"] for w in right_ws)
                x_r = max(w["x1"] for w in right_ws)
                right_lines.append((y, text, y_top, y_bot, x_l, x_r))

        # Emit one block per left-column line (actor roster content)
        # Right-column content (rates/locations) is secondary — attach to preceding left line
        return self._lines_to_individual_blocks(left_lines, right_lines, page_num)

    def _lines_to_individual_blocks(
        self,
        left_lines: list[tuple[int, str, float, float, float, float]],
        right_lines: list[tuple[int, str, float, float, float, float]],
        page_num: int,
    ) -> list[RawBlock]:
        """One block per left-column line; append same-y right column content.
        Right-column lines with no matching left-column line are emitted separately
        so actors that appear only in the right column (e.g. cab drivers) aren't dropped.
        """
        # Build index of right-line content by y
        right_by_y: dict[int, tuple[str, float, float, float, float]] = {}
        for y, text, y_top, y_bot, x_l, x_r in right_lines:
            if y in right_by_y:
                existing_text = right_by_y[y][0]
                right_by_y[y] = (existing_text + " " + text, y_top, y_bot, x_l, x_r)
            else:
                right_by_y[y] = (text, y_top, y_bot, x_l, x_r)

        left_ys: set[int] = set()
        blocks: list[RawBlock] = []
        for y, text, y_top, y_bot, x_l, x_r in left_lines:
            if not text.strip():
                continue
            left_ys.add(y)
            # Attach right-column content from same y (e.g., RATE info)
            right_entry = right_by_y.get(y)
            right_text = right_entry[0].strip() if right_entry else ""
            full_text = (text + "  " + right_text).strip() if right_text else text.strip()
            blocks.append(
                RawBlock(
                    text=full_text,
                    page=page_num,
                    y_top=y_top,
                    y_bottom=y_bot,
                    x_left=x_l,
                    x_right=x_r,
                    line_indices=[y],
                )
            )

        # Emit right-column-only lines that had no matching left-column line
        for y, (text, y_top, y_bot, x_l, x_r) in sorted(right_by_y.items()):
            if y not in left_ys and text.strip():
                blocks.append(
                    RawBlock(
                        text=text.strip(),
                        page=page_num,
                        y_top=y_top,
                        y_bottom=y_bot,
                        x_left=x_l,
                        x_right=x_r,
                        line_indices=[y],
                    )
                )

        # Re-sort all blocks by y_top so the order matches reading order
        blocks.sort(key=lambda b: b.y_top)
        return blocks

    def _lines_to_blocks(
        self,
        lines: list[tuple[int, str, float, float, float, float]],
        page_num: int,
    ) -> list[RawBlock]:
        if not lines:
            return []

        heights = [ln[3] - ln[2] for ln in lines]
        median_h = statistics.median(heights) if heights else 12.0
        gap_threshold = max(1.5 * median_h, 8.0)

        blocks: list[RawBlock] = []
        current: list[tuple[int, str, float, float, float, float]] = []

        for line in lines:
            if not line[1].strip():
                continue
            if not current:
                current.append(line)
            else:
                gap = line[2] - current[-1][3]  # y_top of new - y_bottom of prev
                if gap > gap_threshold:
                    blocks.append(self._make_block(current, page_num))
                    current = [line]
                else:
                    current.append(line)

        if current:
            blocks.append(self._make_block(current, page_num))

        return blocks

    def _make_block(
        self, lines: list[tuple[int, str, float, float, float, float]], page_num: int
    ) -> RawBlock:
        text = "\n".join(ln[1] for ln in lines if ln[1].strip())
        return RawBlock(
            text=text.strip(),
            page=page_num,
            y_top=min(ln[2] for ln in lines),
            y_bottom=max(ln[3] for ln in lines),
            x_left=min(ln[4] for ln in lines),
            x_right=max(ln[5] for ln in lines),
            line_indices=list(range(len(lines))),
        )

    def _snap_y(self, y: int, existing: object) -> int:
        existing_list = list(existing)  # type: ignore[arg-type]
        for ey in existing_list:
            if abs(y - ey) <= 3:
                return ey
        return y

    def _detect_column_split(self, all_x0: list[float], page_width: float) -> float:
        """Find the x coordinate where a major column gap occurs."""
        if not all_x0:
            return page_width * 0.5

        # Look for the largest gap in x0 distribution between 30-70% of page width
        sorted_x = sorted(set(round(x, 0) for x in all_x0))
        mid_low = page_width * 0.3
        mid_high = page_width * 0.7

        best_gap = 0.0
        best_split = page_width * 0.5

        for i in range(1, len(sorted_x)):
            if mid_low <= sorted_x[i] <= mid_high:
                gap = sorted_x[i] - sorted_x[i - 1]
                if gap > best_gap:
                    best_gap = gap
                    best_split = (sorted_x[i] + sorted_x[i - 1]) / 2

        return best_split

    def _load_pymupdf(self, path: Path) -> list[RawBlock]:
        try:
            import fitz  # type: ignore[import-untyped]
        except ImportError:
            logger.warning("pymupdf not available")
            return []

        blocks: list[RawBlock] = []
        doc = fitz.open(str(path))
        for page_num, page in enumerate(doc, start=1):  # type: ignore[call-overload]
            text_blocks = page.get_text("blocks")  # type: ignore[attr-defined]
            for i, tb in enumerate(text_blocks):
                x0, y0, x1, y1, text = tb[0], tb[1], tb[2], tb[3], tb[4]
                if text.strip():
                    blocks.append(
                        RawBlock(
                            text=text.strip(),
                            page=page_num,
                            y_top=float(y0),
                            y_bottom=float(y1),
                            x_left=float(x0),
                            x_right=float(x1),
                            line_indices=[i],
                        )
                    )
        doc.close()
        return blocks
