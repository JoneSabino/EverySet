from .models import ConfidenceTier, ExtractedActor, ExtractedRow

REQUIRED = ["actor_name", "role", "rate_amount"]
OPTIONAL = ["role_type", "phone", "email", "call_time", "union_name", "notes"]
WEIGHTS: dict[str, int] = {f: 3 for f in REQUIRED} | {f: 1 for f in OPTIONAL}


def compute_row_confidence(row: ExtractedRow) -> tuple[float, ConfidenceTier, dict[str, float]]:
    breakdown: dict[str, float] = {}

    for field in REQUIRED + OPTIONAL:
        val = getattr(row, field, None)
        if field == "actor_name":
            breakdown[field] = 1.0 if val else 0.0
        elif field == "role":
            breakdown[field] = 1.0 if val else 0.0
        elif field == "rate_amount":
            breakdown[field] = 1.0 if val is not None else 0.0
        elif field in ("phone", "email", "call_time", "union_name"):
            breakdown[field] = 0.95 if val else 0.0
        elif field == "role_type":
            breakdown[field] = 0.95 if val else 0.0
        elif field == "notes":
            breakdown[field] = 0.0  # optional, doesn't penalize

    score = _weighted_score(breakdown)
    t = _tier(score)
    return score, t, breakdown


def _weighted_score(per_field: dict[str, float]) -> float:
    total = sum(per_field.get(f, 0.0) * WEIGHTS.get(f, 1) for f in WEIGHTS)
    weight_sum = sum(WEIGHTS.values())
    score = total / weight_sum

    missing = sum(1 for f in REQUIRED if per_field.get(f, 0.0) == 0.0)
    if missing > 0:
        score *= 0.5**missing

    return round(min(max(score, 0.0), 1.0), 3)


def _tier(score: float) -> ConfidenceTier:
    if score >= 0.85:
        return "high"
    if score >= 0.60:
        return "medium"
    return "low"


def actor_field_confidences(actor: ExtractedActor) -> dict[str, float]:
    return {
        "actor_name": actor.actor_name.confidence,
        "phone": actor.phone.confidence,
        "email": actor.email.confidence,
        "notes": actor.notes.confidence,
        "rate_override": actor.rate_override_raw.confidence,
        "cancelled": actor.cancelled.confidence,
    }
