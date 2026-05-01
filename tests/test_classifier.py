"""Tests for block classifier."""

from skins_extractor.classifier import classify_blocks
from skins_extractor.models import RawBlock


def _block(text: str, page: int = 1) -> RawBlock:
    return RawBlock(text=text, page=page, y_top=0, y_bottom=10, x_left=0, x_right=500)


class TestClassifyBlocks:
    def test_actor_row_with_phone(self) -> None:
        blocks = [_block("Ralph Francisco 123-456-7890 ralph@test.com")]
        classified = classify_blocks(blocks)
        assert classified[0].kind == "actor_row"
        assert classified[0].classifier_confidence >= 0.90

    def test_section_header_background(self) -> None:
        blocks = [_block("BACKGROUND")]
        classified = classify_blocks(blocks)
        assert classified[0].kind == "section_header"

    def test_section_header_stand_ins(self) -> None:
        blocks = [_block("STAND INS")]
        classified = classify_blocks(blocks)
        assert classified[0].kind == "section_header"

    def test_noise_empty(self) -> None:
        blocks = [_block("")]
        classified = classify_blocks(blocks)
        assert classified[0].kind == "noise"

    def test_actor_row_with_email_only(self) -> None:
        blocks = [_block("Jane Doe jane@example.com")]
        classified = classify_blocks(blocks)
        assert classified[0].kind == "actor_row"

    def test_cancelled_row(self) -> None:
        blocks = [_block("John Smith 310-555-1234 XXX")]
        classified = classify_blocks(blocks)
        assert classified[0].kind == "actor_row"
