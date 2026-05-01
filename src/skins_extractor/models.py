from typing import Literal

from pydantic import BaseModel, Field

RoleType = Literal[
    "stand-in",
    "background",
    "photo double",
    "featured background",
    "special ability",
    "audience",
    "",
]
UnionName = Literal["union", "sag-aftra", "non-union", ""]
ExtractionMethod = Literal[
    "deterministic",
    "fuzzy",
    "section-context",
    "pattern-store",
    "llm-outline",
    "llm-row-fallback",
    "llm-vision",
]
RateUnit = Literal["day_8h", "day_10h", "day_12h", "hourly", "voucher", "flat", ""]
ConfidenceTier = Literal["high", "medium", "low"]


class RawBlock(BaseModel):
    text: str
    page: int
    y_top: float
    y_bottom: float
    x_left: float
    x_right: float
    font_size: float | None = None
    fill_color: tuple[float, float, float] | None = None
    line_indices: list[int] = Field(default_factory=list)


class ClassifiedBlock(BaseModel):
    block: RawBlock
    kind: Literal["legend", "section_header", "actor_row", "noise", "unknown"]
    classifier_confidence: float


class SectionContext(BaseModel):
    role: str
    role_type: RoleType
    call_time: str
    union_name: UnionName
    rate_raw: str
    rate_amount: float | None
    rate_unit: RateUnit
    rate_modifiers: dict = Field(default_factory=dict)
    column_convention: str = ""
    source_blocks: list[int] = Field(default_factory=list)


class FieldExtraction(BaseModel):
    value: str | float | bool | None
    method: ExtractionMethod
    confidence: float
    source: str


class ExtractedActor(BaseModel):
    actor_name: FieldExtraction
    phone: FieldExtraction
    email: FieldExtraction
    notes: FieldExtraction
    rate_override_raw: FieldExtraction
    cancelled: FieldExtraction
    union_name: FieldExtraction = Field(
        default_factory=lambda: FieldExtraction(
            value="", method="deterministic", confidence=0.0, source=""
        )
    )


class ExtractedRow(BaseModel):
    document_name: str
    call_time: str
    union_name: UnionName
    actor_name: str
    role_type: RoleType
    role: str
    rate_raw: str
    rate_amount: float | None
    rate_unit: RateUnit
    rate_modifiers: dict
    phone: str
    email: str
    notes: str
    cancelled: bool
    confidence: float
    confidence_tier: ConfidenceTier
    confidence_breakdown: dict[str, float]
    source: str
    extraction_method: ExtractionMethod


class ProposedPattern(BaseModel):
    pattern_type: Literal["section_header", "actor_row", "rate_inline"]
    regex: str
    description: str
    example_match: str
    example_output: dict


class OutlineResult(BaseModel):
    sections: list[SectionContext]
    suggested_patterns: list[ProposedPattern] = Field(default_factory=list)


class StoredPattern(BaseModel):
    pattern_id: str
    pattern_type: str
    format_fingerprint: str
    regex: str
    description: str
    example_match: str
    example_output: dict
    created_by: str
    status: str
    approved_by: str | None = None
    approved_at: str | None = None
    created_at: str
    match_count: int
    success_count: int
    last_matched_at: str | None = None


class ExtractionRun(BaseModel):
    run_id: str
    document_name: str
    fingerprint: str
    patterns_used: list[str] = Field(default_factory=list)
    llm_calls: int = 0
    rows_extracted: int = 0
    rows_low_confidence: int = 0
    profile: str = "default"
