"""Tests for confidence scoring."""

from skins_extractor.confidence import _tier, _weighted_score, compute_row_confidence
from skins_extractor.models import ExtractedRow


def _make_row(**kwargs: object) -> ExtractedRow:
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
        confidence=0.0,
        confidence_tier="low",
        confidence_breakdown={},
        source="p1:y10",
        extraction_method="deterministic",
    )
    defaults.update(kwargs)
    return ExtractedRow(**defaults)  # type: ignore[arg-type]


class TestWeightedScore:
    def test_all_present(self) -> None:
        score = _weighted_score(
            {
                "actor_name": 1.0,
                "role": 1.0,
                "rate_amount": 1.0,
                "role_type": 0.95,
                "phone": 0.95,
                "email": 0.0,
                "call_time": 0.95,
                "union_name": 0.95,
                "notes": 0.0,
            }
        )
        assert score >= 0.85

    def test_missing_required_field(self) -> None:
        score = _weighted_score(
            {
                "actor_name": 1.0,
                "role": 0.0,
                "rate_amount": 1.0,
            }
        )
        # Missing one required field → 50% penalty
        assert score < 0.5

    def test_all_zero(self) -> None:
        score = _weighted_score(
            {
                k: 0.0
                for k in [
                    "actor_name",
                    "role",
                    "rate_amount",
                    "role_type",
                    "phone",
                    "email",
                    "call_time",
                    "union_name",
                    "notes",
                ]
            }
        )
        assert score == 0.0


class TestTier:
    def test_high(self) -> None:
        assert _tier(0.90) == "high"

    def test_medium(self) -> None:
        assert _tier(0.70) == "medium"

    def test_low(self) -> None:
        assert _tier(0.50) == "low"


class TestComputeRowConfidence:
    def test_full_row(self) -> None:
        row = _make_row()
        score, tier, breakdown = compute_row_confidence(row)
        assert score > 0.5
        assert tier in ("high", "medium")

    def test_missing_actor_name(self) -> None:
        row = _make_row(actor_name="")
        score, tier, breakdown = compute_row_confidence(row)
        # One required field missing → 50% penalty → well below 0.5
        assert score < 0.5
        assert breakdown.get("actor_name", 1.0) == 0.0

    def test_missing_rate(self) -> None:
        row = _make_row(rate_amount=None)
        score, tier, breakdown = compute_row_confidence(row)
        assert score < 0.5
