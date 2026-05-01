"""Tests for deterministic extractor."""

from skins_extractor.extractors.deterministic import extract_actors_deterministic
from skins_extractor.models import ClassifiedBlock, RawBlock, SectionContext


def _actor_block(text: str) -> ClassifiedBlock:
    block = RawBlock(text=text, page=1, y_top=0, y_bottom=10, x_left=0, x_right=500)
    return ClassifiedBlock(block=block, kind="actor_row", classifier_confidence=0.95)


def _ctx() -> SectionContext:
    return SectionContext(
        role="Background",
        role_type="background",
        call_time="7:00AM",
        union_name="union",
        rate_raw="$144/8",
        rate_amount=144.0,
        rate_unit="day_8h",
        rate_modifiers={},
    )


class TestDeterministicExtractor:
    def test_extracts_name_phone_email(self) -> None:
        blocks = [_actor_block("Jane Doe 310-555-1234 jane@test.com")]
        actors = extract_actors_deterministic(blocks, _ctx(), "test.pdf")
        assert len(actors) == 1
        assert "Jane" in str(actors[0].actor_name.value)
        assert actors[0].phone.value == "310-555-1234"
        assert actors[0].email.value == "jane@test.com"

    def test_strips_leading_number(self) -> None:
        blocks = [_actor_block("501 Ralph Francisco 123-456-7890 ralph@test.com")]
        actors = extract_actors_deterministic(blocks, _ctx(), "test.pdf")
        assert "Ralph Francisco" in str(actors[0].actor_name.value)

    def test_cancelled_xxx(self) -> None:
        blocks = [_actor_block("John Smith 310-555-1234 XXX")]
        actors = extract_actors_deterministic(blocks, _ctx(), "test.pdf")
        assert actors[0].cancelled.value is True

    def test_rate_override(self) -> None:
        blocks = [_actor_block("Jane Doe 310-555-1234 $200/8")]
        actors = extract_actors_deterministic(blocks, _ctx(), "test.pdf")
        assert actors[0].rate_override_raw.value == "$200/8"

    def test_taft_hartley_flag(self) -> None:
        blocks = [_actor_block("Rose Sevilla 555-778-5544 TH")]
        actors = extract_actors_deterministic(blocks, _ctx(), "test.pdf")
        assert "Taft Hartley" in str(actors[0].notes.value)

    def test_empty_block_skipped(self) -> None:
        blocks = [_actor_block("")]
        actors = extract_actors_deterministic(blocks, _ctx(), "test.pdf")
        assert len(actors) == 0
