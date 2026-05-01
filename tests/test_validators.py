"""Tests for row validator."""

from skins_extractor.models import ExtractedRow
from skins_extractor.validators import validate_row


def _row(**kwargs: object) -> ExtractedRow:
    defaults = dict(
        document_name="test.pdf",
        call_time="7:00AM",
        union_name="union",
        actor_name="Jane Doe",
        role_type="background",
        role="Background",
        rate_raw="$144/8",
        rate_amount=144.0,
        rate_unit="day_8h",
        rate_modifiers={},
        phone="310-555-1234",
        email="",
        notes="",
        cancelled=False,
        confidence=0.90,
        confidence_tier="high",
        confidence_breakdown={},
        source="p1:y0",
        extraction_method="deterministic",
    )
    defaults.update(kwargs)
    return ExtractedRow(**defaults)  # type: ignore[arg-type]


class TestValidateRow:
    def test_valid_row_no_errors(self) -> None:
        assert validate_row(_row()) == []

    def test_bad_phone_format(self) -> None:
        errors = validate_row(_row(phone="5551234"))
        assert any("phone" in e for e in errors)

    def test_empty_phone_ok(self) -> None:
        assert validate_row(_row(phone="")) == []

    def test_valid_role_types_pass(self) -> None:
        # Pydantic enforces Literal at construction; validator only sees valid enum values
        for rt in ("background", "stand-in", "photo double", ""):
            assert validate_row(_row(role_type=rt)) == []  # type: ignore[arg-type]

    def test_valid_union_names_pass(self) -> None:
        for u in ("union", "sag-aftra", "non-union", ""):
            assert validate_row(_row(union_name=u)) == []  # type: ignore[arg-type]

    def test_confidence_out_of_range(self) -> None:
        errors = validate_row(_row(confidence=1.5))
        assert any("confidence" in e for e in errors)

    def test_empty_actor_name(self) -> None:
        errors = validate_row(_row(actor_name=""))
        assert any("actor_name" in e for e in errors)
