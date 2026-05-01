# Skins Extractor — Implementation Plan

> PDF roster extraction pipeline for EverySet take-home assessment.
> This plan is the blueprint. Read top-to-bottom, implement phase-by-phase.

---

## Table of Contents

1. [Goals & Non-Goals](#1-goals--non-goals)
2. [Locked Decisions](#2-locked-decisions-recap-of-the-design-interview)
3. [Architecture](#3-architecture)
4. [Repo Layout](#4-repo-layout)
5. [Data Models](#5-data-models)
6. [Configuration](#6-configuration)
7. [Pipeline Stage Details](#7-pipeline-stage-details)
8. [Pattern Store](#8-pattern-store)
9. [LLM Layer](#9-llm-layer)
10. [Edge Cases & Normalization Rules](#10-edge-cases--normalization-rules)
11. [Confidence Model](#11-confidence-model)
12. [Output Schema](#12-output-schema)
13. [Testing Strategy](#13-testing-strategy)
14. [Benchmark Harness](#14-benchmark-harness)
15. [CLI Surface](#15-cli-surface)
16. [Implementation Phases](#16-implementation-phases-build-order)
17. [Dependencies](#17-dependencies)
18. [Deliverables Checklist](#18-deliverables-checklist)
19. [Productionization Notes](#19-productionization-notes-for-readme)
20. [Known Limitations](#20-known-limitations)

---

## 1. Goals & Non-Goals

### Goals

- Extract structured roster data from PDF (and CSV) "Skins" exports into a clean, normalized CSV.
- Two output CSVs: `clean.csv` (import-ready) + `debug.csv` (full superset with confidence, source, method).
- Per-row + per-field confidence scoring.
- Architecture that scales to new formats without per-format code:
  - Deterministic-first: regex, fuzzy enum matching, structural rules.
  - LLM only where format genuinely varies (section detection) or determinism fails (jumbled extraction).
  - Pattern store (DuckDB) learns structures across runs; subsequent docs hit cache.
- Multi-vendor LLM abstraction (Anthropic, OpenAI, Google, xAI).
- Source attribution + structured logging + validation.
- Visual benchmark report.

### Non-Goals

- Cross-document deduplication (semantically wrong — each PDF is a distinct production day).
- Real-time streaming pipeline (batch processing is fine).
- Web UI for the curator (CLI only).
- OCR for handwritten/scanned-paper artifacts beyond what vision LLMs handle.
- Production deployment automation (Docker / k8s — leave as README "next steps").

---

## 2. Locked Decisions (Recap of the Design Interview)

| # | Topic | Decision |
|---|---|---|
| Q1 | Language | **Python 3.12+** |
| Q2 | PDF extraction | **`pdfplumber`** primary, `pymupdf` fallback, vision LLM as last-resort OCR |
| Q3 | LLM routing unit | **Per-section** (header + actor rows as a unit) |
| Q4 | Section detection | **Lexical-first → DuckDB pattern store lookup → LLM outliner fallback** |
| Q5 | CSV output | **Two files**: `clean.csv` (matches example exactly + confidence) + `debug.csv` (full superset) |
| Q6 | Confidence | **Per-field [0,1] → row aggregate (weighted mean with required-field penalty), tier (high/med/low)** |
| Q6b | Fuzzy matching | **`rapidfuzz`** with `token_set_ratio` for enum mapping (`role_type`, `union_name`) |
| Q7 | Edge cases | Color-cancellation, composite/voucher rates, multi-line, OCR fallback, regression harness — all IN |
| Q8 | LLM providers | **4 adapters: Anthropic, OpenAI, Google, xAI**. 5 profiles: `default` / `best_of_breed` / `cost` / `openai_only` / `high_accuracy` |
| Q8b | Default profile | **`default` (Anthropic-only)** for ease-of-run; README explains how to switch |
| Q9 | Repo layout | `src/` layout, modular per-stage |
| Q9b | Ground truth | LLM-generated first-pass, manually reviewed, frozen in `tests/fixtures/expected/` |
| Q9c | LLM in CI | **VCR cassettes** — recorded once, replayed in CI |
| Q9d | Benchmark output | **Static HTML dashboard** (jinja2 + matplotlib) + raw CSV |
| — | Dedup | Within-section IN, cross-section IN-no-merge, near-duplicate flag IN, cross-doc OUT (correctness) |
| — | Curator UI | **CLI subcommands** `patterns list/show/approve/reject` IN; web UI OUT |
| — | Slack notify | **Webhook stub** IN, gated by env var |

---

## 3. Architecture

```
                    ┌─────────────────────────┐
   PDF / CSV ────►  │ 1. Loader               │
                    │   pdfplumber → bbox+text│
                    │   pymupdf fallback      │
                    │   csv.reader for .csv   │
                    └────────────┬────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │ 2. Fingerprint          │
                    │   Structural hash:      │
                    │   table_count, headers, │
                    │   font signatures, etc. │
                    └────────────┬────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │ 3. Section Detector     │
                    │  ┌────────────────────┐ │
                    │  │ a. Lexical (rules) │ │  ← cheap, fast path
                    │  └─────────┬──────────┘ │
                    │            │ if low conf │
                    │  ┌─────────▼──────────┐ │
                    │  │ b. Pattern store   │ │  ← learned patterns
                    │  │    lookup (DuckDB) │ │
                    │  └─────────┬──────────┘ │
                    │            │ if no match│
                    │  ┌─────────▼──────────┐ │
                    │  │ c. LLM outliner    │ │  ← novel formats only
                    │  │   + propose patterns│ │
                    │  └────────────────────┘ │
                    └────────────┬────────────┘
                                 ▼
              ┌──────────────────────────────────┐
              │ 4. Per-section processing        │
              │  for each detected section:      │
              │   ┌──────────────────────────┐   │
              │   │ a. Det. field extractor  │   │
              │   │    regex + rapidfuzz     │   │
              │   └──────────┬───────────────┘   │
              │              │ if any required   │
              │              │ row field missing │
              │   ┌──────────▼───────────────┐   │
              │   │ b. LLM row-fallback      │   │
              │   │    (section block only)  │   │
              │   └──────────────────────────┘   │
              └────────────┬─────────────────────┘
                           ▼
              ┌─────────────────────────┐
              │ 5. Section-context join │
              │    propagate role,      │
              │    role_type, call_time,│
              │    union, rate          │
              └────────────┬────────────┘
                           ▼
              ┌─────────────────────────┐
              │ 6. Normalizers          │
              │   phone, rate, name,    │
              │   enums                 │
              └────────────┬────────────┘
                           ▼
              ┌─────────────────────────┐
              │ 7. Confidence scorer    │
              │   per-field + per-row   │
              └────────────┬────────────┘
                           ▼
              ┌─────────────────────────┐
              │ 8. Validators           │
              │   schema, ranges, enums │
              └────────────┬────────────┘
                           ▼
              ┌─────────────────────────┐
              │ 9. Writers              │
              │   clean.csv + debug.csv │
              └─────────────────────────┘
```

---

## 4. Repo Layout

```
skins-extractor/
├── pyproject.toml
├── README.md
├── PLAN.md                        # this file
├── LICENSE
├── .gitignore
├── .env.example
├── Makefile
├── config/
│   ├── default.yaml
│   ├── profiles.yaml
│   └── prompts/
│       ├── outliner.system.md
│       ├── outliner.user.md
│       ├── row_fallback.system.md
│       ├── row_fallback.user.md
│       └── vision_fallback.system.md
├── src/skins_extractor/
│   ├── __init__.py
│   ├── cli.py
│   ├── pipeline.py
│   ├── config.py
│   ├── models.py
│   ├── logging_config.py
│   ├── loaders/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── pdf.py
│   │   └── csv.py
│   ├── fingerprint.py
│   ├── segmenter.py
│   ├── classifier.py
│   ├── extractors/
│   │   ├── __init__.py
│   │   ├── deterministic.py
│   │   └── llm_extractor.py
│   ├── normalizers/
│   │   ├── __init__.py
│   │   ├── phone.py
│   │   ├── rate.py
│   │   ├── name.py
│   │   └── enums.py
│   ├── confidence.py
│   ├── validators.py
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── provider.py
│   │   ├── anthropic_adapter.py
│   │   ├── openai_adapter.py
│   │   ├── google_adapter.py
│   │   ├── xai_adapter.py
│   │   └── router.py
│   ├── pattern_store/
│   │   ├── __init__.py
│   │   ├── db.py
│   │   ├── schema.sql
│   │   └── regression.py
│   ├── notifications/
│   │   ├── __init__.py
│   │   └── slack.py
│   └── writers.py
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   │   ├── pdfs/                  # 5 sample PDFs
│   │   ├── expected/              # ground truth CSVs
│   │   ├── synthetic/             # crafted micro-PDFs for unit tests
│   │   └── cassettes/             # VCR-recorded LLM responses
│   ├── test_loaders.py
│   ├── test_segmenter.py
│   ├── test_classifier.py
│   ├── test_normalizers.py
│   ├── test_extractors.py
│   ├── test_confidence.py
│   ├── test_pattern_store.py
│   ├── test_llm_adapters.py
│   └── test_e2e.py
├── bench/
│   ├── run.py
│   ├── report.py                  # HTML dashboard generator
│   ├── templates/
│   │   └── dashboard.html.j2
│   └── results/                   # generated; gitignored
├── output/                        # generated; gitignored
├── data/
│   ├── input/                     # 5 sample PDFs (bundled)
│   └── patterns.duckdb            # gitignored; created on first run
└── prompts/                       # mirror of config/prompts (referenced)
```

---

## 5. Data Models

All Pydantic v2. Strict types, `Literal` for enums.

```python
# src/skins_extractor/models.py

from typing import Literal, Optional
from pydantic import BaseModel, Field

RoleType = Literal[
    "stand-in", "background", "photo double",
    "featured background", "special ability", "audience", ""
]
UnionName = Literal["union", "sag-aftra", "non-union", ""]
ExtractionMethod = Literal[
    "deterministic", "fuzzy", "section-context",
    "pattern-store", "llm-outline", "llm-row-fallback", "llm-vision"
]
RateUnit = Literal["day_8h", "hourly", "voucher", "flat", ""]
ConfidenceTier = Literal["high", "medium", "low"]

class RawBlock(BaseModel):
    """A chunk of text from the loader, with bbox metadata."""
    text: str
    page: int
    y_top: float
    y_bottom: float
    x_left: float
    x_right: float
    font_size: Optional[float] = None
    fill_color: Optional[tuple[float, float, float]] = None  # RGB 0-1
    line_indices: list[int] = Field(default_factory=list)

class ClassifiedBlock(BaseModel):
    block: RawBlock
    kind: Literal["legend", "section_header", "actor_row", "noise", "unknown"]
    classifier_confidence: float

class SectionContext(BaseModel):
    """Resolved section metadata propagated to its actor rows."""
    role: str
    role_type: RoleType
    call_time: str
    union_name: UnionName
    rate_raw: str
    rate_amount: Optional[float]
    rate_unit: RateUnit
    rate_modifiers: dict = Field(default_factory=dict)
    source_blocks: list[int]  # indices into the block list

class FieldExtraction(BaseModel):
    """One field's value + how we got it."""
    value: str | float | bool | None
    method: ExtractionMethod
    confidence: float
    source: str  # e.g., "p1:L23"

class ExtractedActor(BaseModel):
    actor_name: FieldExtraction
    phone: FieldExtraction
    email: FieldExtraction
    notes: FieldExtraction
    rate_override_raw: FieldExtraction
    cancelled: FieldExtraction

class ExtractedRow(BaseModel):
    """Final shape per output row, before CSV serialization."""
    document_name: str
    call_time: str
    union_name: UnionName
    actor_name: str
    role_type: RoleType
    role: str
    rate_raw: str
    rate_amount: Optional[float]
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
    """LLM-generated pattern suggestion."""
    pattern_type: Literal["section_header", "actor_row", "rate_inline"]
    regex: str
    description: str
    example_match: str
    example_output: dict

class OutlineResult(BaseModel):
    """LLM outliner response."""
    sections: list[SectionContext]
    suggested_patterns: list[ProposedPattern]
```

---

## 6. Configuration

### `config/profiles.yaml`

```yaml
# Active profile selected by env var SKINS_PROFILE or --profile flag.
# Default if unset: "default"

profiles:

  default:
    description: "Single-vendor Anthropic. Easiest first-run; one API key."
    outliner:
      provider: anthropic
      model: claude-sonnet-4-6
      enable_caching: true
      max_tokens: 4096
    row_fallback:
      provider: anthropic
      model: claude-haiku-4-5-20251001
      enable_caching: true
      max_tokens: 1024
    vision_fallback:
      provider: anthropic
      model: claude-sonnet-4-6
      max_tokens: 4096

  best_of_breed:
    description: "Mix providers — best price/capability per task. Requires 3 API keys."
    outliner:        { provider: openai,    model: gpt-5,                    max_tokens: 4096 }
    row_fallback:    { provider: google,    model: gemini-2.5-flash-lite,    max_tokens: 1024 }
    vision_fallback: { provider: anthropic, model: claude-sonnet-4-6,        max_tokens: 4096 }

  cost:
    description: "Cheapest credible across the board. Single SDK (xAI Grok)."
    outliner:        { provider: xai, model: grok-4.1-fast, max_tokens: 4096 }
    row_fallback:    { provider: xai, model: grok-4.1-fast, max_tokens: 1024 }
    vision_fallback: { provider: xai, model: grok-4.1-fast, max_tokens: 4096 }

  openai_only:
    description: "OpenAI-only. For orgs sanctioned to OpenAI."
    outliner:        { provider: openai, model: gpt-5,        max_tokens: 4096 }
    row_fallback:    { provider: openai, model: gpt-4o-mini,  max_tokens: 1024 }
    vision_fallback: { provider: openai, model: gpt-5,        max_tokens: 4096 }

  high_accuracy:
    description: "Maximum quality. Use only if benchmark proves it."
    outliner:        { provider: anthropic, model: claude-opus-4-7, max_tokens: 4096 }
    row_fallback:    { provider: openai,    model: gpt-5,           max_tokens: 1024 }
    vision_fallback: { provider: anthropic, model: claude-opus-4-7, max_tokens: 4096 }

# Pipeline behavior — provider-agnostic
pipeline:
  trust_mode: human_approval        # human_approval | auto_trust
  pattern_store_path: data/patterns.duckdb
  llm_outline_threshold: 0.6        # below this lexical confidence → LLM outline
  fuzzy_threshold: 0.70             # below this → no fuzzy match, route to LLM
  fuzzy_high_threshold: 0.95        # above this → effectively exact match
  ocr_min_chars: 50                 # below this from pdfplumber → pymupdf fallback
  enable_color_detection: true       # detect red text/fill for cancellations
  log_level: INFO

# Notifications
notifications:
  slack_webhook_url: ${SLACK_WEBHOOK_URL:-}   # silent no-op if unset

# Output
output:
  clean_csv: output/clean.csv
  debug_csv: output/debug.csv
  log_file:  output/extraction.log
```

### `.env.example`

```bash
# At least ONE of these is required, depending on selected profile:
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GOOGLE_API_KEY=
XAI_API_KEY=

# Optional
SLACK_WEBHOOK_URL=
SKINS_PROFILE=default
SKINS_LOG_LEVEL=INFO
```

---

## 7. Pipeline Stage Details

### Stage 1: Loaders

**`loaders/pdf.py`**
- Uses `pdfplumber.open(path)` to get per-page `chars` (with bbox + font + color).
- Groups chars into lines by y-coordinate (within `±2pt`).
- Groups lines into blocks by y-gap heuristic: a gap > `1.5 × median_line_height` ends a block.
- Returns `list[RawBlock]`.
- If `extract_text()` total length < `pipeline.ocr_min_chars` → fall through to `pymupdf` (`fitz`).
- If `pymupdf` also returns empty → flag for vision-LLM OCR (Stage 4 handles).

**`loaders/csv.py`**
- For Skins 3-style native CSV: `csv.reader`, skip empty rows.
- Emit `RawBlock` per row group (collapse consecutive rows with same section header).
- bbox info synthesized (page=1, y based on row index).

**`loaders/base.py`**
- Common `Loader` Protocol; route by file extension.

### Stage 2: Fingerprint

**`fingerprint.py`**
- Computes a structural hash of the document for pattern store lookup.
- Inputs: total block count, count of section-header-candidate blocks, count of phone-number-bearing blocks, font-size histogram (top 3 sizes), presence-of-table-bordered-areas (pdfplumber's `find_tables()`).
- Output: a 12-char base32 hash.
- Two docs with similar layouts share a fingerprint; truly novel formats get a unique one.

### Stage 3: Section Detector

**`classifier.py`**

Detection chain (in order):
1. **Lexical rules** (`classifier.lexical_detect`):
   - A block is a `section_header` if:
     - All-caps OR title-case
     - Contains role_type keyword (fuzzy `token_set_ratio ≥ 0.85` against the enum + synonyms `BG`, `PD`, `SpA`, `ND`, `Ins`, etc.)
     - **No** phone-number regex match
     - **No** email regex match
   - Special handlers for known patterns: `CALL TIME: HH:MM`, `^\d+ROLE_KEYWORDS`, `Special.*Rate.*\$`.
2. **Pattern store lookup** (`pattern_store.find_by_fingerprint`):
   - If fingerprint matches an `approved` pattern, run its regex against the document text.
   - Use those section boundaries.
3. **LLM outliner** (`extractors.llm_extractor.outline`):
   - Send full document text + the lexical attempts (as context).
   - Receive structured `OutlineResult` + `suggested_patterns`.
   - Insert suggested patterns into store with `status='pending_review'` (or `'approved'` if `trust_mode=auto_trust`).

**Confidence threshold for fallback:** if lexical + pattern-store together identify fewer sections than expected (heuristic: doc has many phone numbers but few section headers), escalate to LLM.

### Stage 4: Per-Section Processing

For each detected section:

**`extractors/deterministic.py`**
- For each candidate actor row block:
  - **Phone**: `re.search(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', text)` + cleanup.
  - **Email**: standard email regex.
  - **Rate (row-level override)**: `re.search(r'\$(\d+)(?:/(\d+))?', text)`; also detect "voucher", "min", "/hr".
  - **Name**: extract by removing all matched fields from text + stripping leading numeric prefix (`^\d+\s`); apply name-ordering heuristic (see below).
- Emit `ExtractedActor` with per-field `FieldExtraction`.
- Mark missing required fields → flag for LLM row-fallback.

**`extractors/llm_extractor.py` — row fallback**
- Triggered when any required field of any row in the section is missing.
- Send: section header text + raw section blocks + the partial extraction so far.
- Receive: filled-in actor list with confidence per field.
- Merge results, marking method=`llm-row-fallback`.

### Stage 5: Section-Context Join

**`pipeline.py`**
- For each actor in each section, fill missing top-level fields from `SectionContext`:
  - If `actor.rate_override_raw` is empty → use `section.rate_raw`, `section.rate_amount`, `section.rate_unit`.
  - `role`, `role_type`, `call_time`, `union_name` always come from section unless actor row has its own.
- Method tag: `section-context`.

### Stage 6: Normalizers

**`normalizers/phone.py`**
- Strip non-digits.
- If 10 digits → format `XXX-XXX-XXXX`.
- If 11 digits starting with `1` → strip and format.
- Else → return empty + log warning.

**`normalizers/rate.py`**
- Parse `rate_raw` into:
  - `rate_amount`: numeric base (first `$\d+` or unprefixed amount)
  - `rate_unit`: detect from suffix (`/8` → `day_8h`, `/hr` → `hourly`, "voucher" → `voucher`, otherwise `flat`)
  - `rate_modifiers`: dict for bumps (`+250`), minimums (`min 4 hrs`), adjustments (`$150 adjustment`)

**`normalizers/name.py`**
- Detect column header convention from section context if available.
- Strip leading numeric prefixes (CI#, sequence numbers).
- If "Last, First" detected (comma) → flip.
- If section had "LAST FIRST" header → assume two tokens, flip to "First Last".
- Default: no flip.

**`normalizers/enums.py`**
- `role_type`: rapidfuzz `process.extractOne` against canonical enum + synonyms (synonym map below).
  - Score ≥ 0.95 → exact, confidence 0.95
  - Score ≥ 0.85 → strong, confidence 0.85
  - Score ≥ 0.70 → weak, confidence 0.70
  - Below → return `""`, confidence 0.0
- `union_name`: same approach against `union | sag-aftra | non-union`.

**Synonym map (role_type):**
```python
SYNONYMS = {
    "stand-in": ["stand in", "stand-in", "standin", "stand ins", "s/i", "si"],
    "background": ["background", "bg", "nd peds", "nd", "atmosphere", "extras"],
    "photo double": ["photo double", "pd", "p/d", "photo doubles"],
    "featured background": ["featured background", "featured bg", "featured"],
    "special ability": ["special ability", "spa", "sp ab"],
    "audience": ["audience", "audience members"],
}
SYNONYMS_UNION = {
    "union": ["union", "sag", "sag-aftra", "sag aftra", "sag/aftra"],
    "sag-aftra": ["sag-aftra", "sag aftra", "sag/aftra"],  # finer-grained if needed
    "non-union": ["non-union", "non union", "nu", "non-u", "nonunion"],
}
```

### Stage 7: Confidence Scorer

See [Section 11](#11-confidence-model).

### Stage 8: Validators

**`validators.py`**
- `phone` matches `^\d{3}-\d{3}-\d{4}$` or empty
- `rate_amount` is numeric or `None`
- `role_type ∈` enum
- `union_name ∈` enum
- `confidence ∈ [0, 1]`
- `actor_name` non-empty (else assertion: row should have been dropped)
- `cancelled` is bool
- Emit per-row validation errors to log; do NOT drop rows on validation failure (drop at `actor_name` empty only).

### Stage 9: Writers

**`writers.py`**
- `clean.csv` columns: `document_name, call_time, union_name, actor_name, role_type, role, rate, phone, confidence`
  - `rate` = `rate_raw` (matches example in spec)
  - Excludes rows where `cancelled=True`
- `debug.csv` columns: full `ExtractedRow` schema.
- Both use `csv.DictWriter`, UTF-8, `quoting=csv.QUOTE_MINIMAL`.

---

## 8. Pattern Store

### Schema (`pattern_store/schema.sql`)

```sql
CREATE TABLE IF NOT EXISTS extraction_patterns (
  pattern_id          TEXT PRIMARY KEY,        -- UUID
  pattern_type        TEXT NOT NULL,           -- 'section_header' | 'actor_row' | 'rate_inline'
  format_fingerprint  TEXT NOT NULL,
  regex               TEXT NOT NULL,
  description         TEXT,
  example_match       TEXT,
  example_output      JSON,
  created_by          TEXT NOT NULL,           -- 'llm' | 'human'
  status              TEXT NOT NULL DEFAULT 'pending_review',
                      -- 'pending_review' | 'approved' | 'rejected' | 'deprecated'
  approved_by         TEXT,
  approved_at         TIMESTAMP,
  created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  match_count         INTEGER DEFAULT 0,
  success_count       INTEGER DEFAULT 0,
  last_matched_at     TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_patterns_fingerprint
  ON extraction_patterns(format_fingerprint, status);

CREATE INDEX IF NOT EXISTS idx_patterns_status
  ON extraction_patterns(status);

CREATE TABLE IF NOT EXISTS extraction_runs (
  run_id              TEXT PRIMARY KEY,
  document_name       TEXT NOT NULL,
  fingerprint         TEXT NOT NULL,
  patterns_used       JSON,                    -- array of pattern_ids
  llm_calls           INTEGER DEFAULT 0,
  rows_extracted      INTEGER DEFAULT 0,
  rows_low_confidence INTEGER DEFAULT 0,
  profile             TEXT,
  ran_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### `pattern_store/db.py`

```python
class PatternStore:
    def __init__(self, db_path: str): ...
    def insert(self, pattern: ProposedPattern, fingerprint: str,
               status: Literal["pending_review", "approved"]) -> str: ...
    def find_by_fingerprint(self, fingerprint: str,
                            status: str = "approved") -> list[StoredPattern]: ...
    def update_match_stats(self, pattern_id: str, success: bool) -> None: ...
    def list_pending(self) -> list[StoredPattern]: ...
    def approve(self, pattern_id: str, approver: str) -> None: ...
    def reject(self, pattern_id: str, reason: str) -> None: ...
    def deprecate(self, pattern_id: str) -> None: ...
    def record_run(self, run: ExtractionRun) -> None: ...
```

### Regression validation (`pattern_store/regression.py`)

- Before promoting a pattern to `approved` (auto-trust mode), run its regex against `tests/fixtures/expected/*.csv`'s source PDFs.
- Count: matches that align with expected rows / total expected rows = `pattern_precision`.
- If `pattern_precision >= 0.9` and no false-positive matches in unrelated sections → approve.
- Else → status stays `pending_review`, regardless of trust mode.

---

## 9. LLM Layer

### `llm/provider.py`

```python
from typing import Protocol
from pydantic import BaseModel

class LLMProvider(Protocol):
    def complete_json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        cache_system: bool = True,
        max_tokens: int = 4096,
    ) -> BaseModel: ...

    def complete_vision_json(
        self,
        system: str,
        user: str,
        image_bytes: bytes,
        schema: type[BaseModel],
        max_tokens: int = 4096,
    ) -> BaseModel: ...
```

### Per-provider adapter notes

| Adapter | JSON-mode mechanism | Caching mechanism |
|---|---|---|
| `anthropic_adapter.py` | `tools=[...]` with strict input_schema; `tool_choice={"type":"tool","name":"..."}` | `cache_control={"type":"ephemeral"}` on system block |
| `openai_adapter.py` | `response_format={"type":"json_schema","json_schema":{"strict":True,"schema":...}}` | Implicit prompt caching (automatic above 1024 tokens) |
| `google_adapter.py` | `response_mime_type="application/json", response_schema=...` | `caching.cached_contents.create(...)` for system |
| `xai_adapter.py` | OpenAI-compatible `response_format={"type":"json_schema",...}` | Automatic |

### Prompts (`config/prompts/`)

**`outliner.system.md`** (cached):
- Role: "You are a roster extraction assistant."
- Schema definition (rendered from Pydantic).
- Enum lists for `role_type`, `union_name`.
- Instructions:
  - Identify section boundaries.
  - For each section, extract role, role_type (use the enum), call_time, rate, union.
  - Identify actor rows with name, phone, email, notes.
  - **Propose patterns** (regex + description + example) for any consistent structure you observed.
  - Be conservative about pattern proposals — only suggest what you'd be willing to apply to a similar future document.
  - Output strict JSON matching the provided schema.

**`outliner.user.md`** (per-call, NOT cached):
- The raw text of the document (with line numbers for source attribution).
- Pre-existing extraction attempts from the lexical layer (as hints).
- Document fingerprint.

**`row_fallback.system.md`** (cached):
- Role: "Extract actor details from the following section block."
- Section context (role, role_type, rate from section header).
- Schema for actor list.

**`row_fallback.user.md`** (per-call):
- The raw block text.
- Partially-extracted actors (with the holes the deterministic layer couldn't fill).

**`vision_fallback.system.md`** (cached):
- Role: "OCR + extract roster data from this image."
- Schema.

### `llm/router.py`

```python
class LLMRouter:
    def __init__(self, profile: ProfileConfig):
        self.outliner = build_provider(profile.outliner)
        self.row_fallback = build_provider(profile.row_fallback)
        self.vision = build_provider(profile.vision_fallback)

    def outline(self, document_text: str, fingerprint: str,
                hints: list[SectionContext]) -> OutlineResult: ...

    def fill_section(self, section_text: str, context: SectionContext,
                     partial_actors: list[ExtractedActor]) -> list[ExtractedActor]: ...

    def vision_ocr(self, page_image: bytes) -> str: ...
```

---

## 10. Edge Cases & Normalization Rules

| # | Edge case | Handling |
|---|---|---|
| 1 | Same actor in multiple sections | Keep all rows; not deduped (different role assignments) |
| 2 | `XXX` cancellation marker | Detect token; set `cancelled=True`; **excluded** from `clean.csv`, included in `debug.csv` |
| 3 | RED-text/highlight cancellation | pdfplumber `non_stroking_color` ≈ `(R>0.7, G<0.3, B<0.3)` per char in row → set `cancelled=True` |
| 4 | Per-actor flags (`TH`, `SR`, `V`, `SpA`) | Token-spot in row text; expand into `notes` (e.g., "Taft Hartley; Self Reporting"); `SpA` → also fuzzy-bumps role_type to `special ability` |
| 5 | Row-level rate override | If row text contains its own `$\d+/\d+` distinct from section rate → use row rate |
| 6 | Composite rate `$224/8 + 250` | `rate_amount=224`, `rate_modifiers={"bump": 250}`, `rate_raw="$224/8 + 250"` |
| 7 | Voucher rate `VOUCHER + $80/hr (min 4 hrs)` | `rate_amount=80`, `rate_unit="hourly"`, `rate_modifiers={"voucher": true, "min_hours": 4}` |
| 8 | Phone formats `(818) 208-5757`, `122.334.5566`, `777) 766-3666` | Strip non-digits, validate 10-digit, format `XXX-XXX-XXXX` |
| 9 | `LAST FIRST` column header | Detected from section header line above table → flip during normalize |
| 10 | Numeric prefix on names (`1 Francisco`, `501 Ralph`) | Strip leading `^\d+\s` |
| 11 | Sub-types like `SAG Dako PD` | Parent (`Photo Doubles`) → role_type; sub → `role` field as character/scene |
| 12 | Header/footer noise | Drop blocks with no actor signals (no phone, email, name-pattern, or role keyword) |
| 13 | Empty CSV separator rows | Skip |
| 14 | Multi-line entries (notes wrap) | Group by y-coord proximity within section blocks |
| 15 | Email with `+N` test convention | Don't dedupe on email — they're distinct testing entries |
| 16 | Scrambled-column text (Skins 1) | Bbox-aware grouping; if still chaotic → LLM row-fallback |
| 17 | Near-duplicate names (`Aquino` vs `Aquiono`) | rapidfuzz ratio < 1.0 but > 0.85 within doc → flag in log; don't auto-merge |
| 18 | Missing required fields | `actor_name` empty → drop. `rate` or `role` empty → include with confidence penalty |
| 19 | Native CSV input (Skins 3) | Bypass pdfplumber; route to `loaders/csv.py` |
| 20 | Empty pdfplumber output | `pymupdf` fallback → if also empty, vision-LLM OCR |
| 21 | Sub-section "Special Fitting Rate $125" | Treat as a section context override; rate_amount=125 |

---

## 11. Confidence Model

### Per-field score

| Source | Score |
|---|---|
| Regex match on canonical pattern | 1.0 |
| Fuzzy enum match, ratio ≥ 0.95 | 0.95 |
| Propagated from section header | 0.95 |
| Propagated from approved DuckDB pattern | 0.95 |
| Fuzzy enum match, ratio 0.85–0.95 | 0.85 |
| Extracted by LLM outliner | 0.85 |
| Propagated from a separate legend (e.g., Skins 5 rate table) | 0.85 |
| Extracted by LLM row-level fallback | 0.80 |
| LLM-suggested pattern (`pending_review`) | 0.75 |
| Fuzzy enum match, ratio 0.70–0.85 | 0.70 |
| Regex weak/partial match | 0.70 |
| Fuzzy ratio < 0.70 → no match → fall through to LLM | — |
| Field empty / not extracted | 0.0 |

### Row aggregate

```python
REQUIRED = ["actor_name", "role", "rate_amount"]
OPTIONAL = ["role_type", "phone", "email", "call_time", "union_name", "notes"]
WEIGHTS = {f: 3 for f in REQUIRED} | {f: 1 for f in OPTIONAL}

def row_score(per_field: dict[str, float]) -> float:
    total = sum(per_field.get(f, 0.0) * WEIGHTS[f] for f in WEIGHTS)
    weight_sum = sum(WEIGHTS.values())
    score = total / weight_sum

    missing = sum(1 for f in REQUIRED if per_field.get(f, 0.0) == 0.0)
    if missing > 0:
        score *= (0.5 ** missing)

    return round(min(max(score, 0.0), 1.0), 3)

def tier(score: float) -> ConfidenceTier:
    if score >= 0.85: return "high"
    if score >= 0.60: return "medium"
    return "low"
```

---

## 12. Output Schema

### `clean.csv` (matches assignment example exactly + confidence)

| Column | Type | Notes |
|---|---|---|
| `document_name` | str | Source filename |
| `call_time` | str | `"7:00AM"`-style; empty if absent |
| `union_name` | str | `union` / `sag-aftra` / `non-union` / empty |
| `actor_name` | str | Required |
| `role_type` | str | Enum value or empty |
| `role` | str | Free-form |
| `rate` | str | `rate_raw` (e.g., `"$144/8"`, `"150/8"`) |
| `phone` | str | `XXX-XXX-XXXX` or empty |
| `confidence` | float | [0, 1] |

Cancelled rows excluded.

### `debug.csv` (full superset)

All clean columns plus:

| Column | Type | Notes |
|---|---|---|
| `email` | str | |
| `notes` | str | Includes expanded flags |
| `rate_amount` | float | Numeric base |
| `rate_unit` | str | `day_8h` / `hourly` / `voucher` / `flat` / empty |
| `rate_modifiers` | JSON | `{"bump": 250, "min_hours": 4, ...}` |
| `cancelled` | bool | |
| `confidence_tier` | str | `high` / `medium` / `low` |
| `confidence_breakdown` | JSON | Per-field scores |
| `source` | str | `"p1:L23-25"` |
| `extraction_method` | str | `deterministic` / `llm-outline` / etc. |

---

## 13. Testing Strategy

### Test categories

| Category | Location | Speed | LLM? |
|---|---|---|---|
| Unit | `tests/test_*.py` | <1s each | No |
| Integration (synthetic) | `tests/test_e2e.py::test_synthetic_*` | <5s each | No |
| E2E with cassettes | `tests/test_e2e.py::test_real_fixtures` | <30s total | Replayed |
| Live benchmark | `bench/run.py` | minutes | Yes (real) |

### Unit test coverage targets

- `normalizers/phone.py`: 10+ test cases (every format observed + edge cases)
- `normalizers/rate.py`: 8+ test cases (composite, voucher, hourly, simple, missing)
- `normalizers/name.py`: 6+ test cases (Last First, First Last, with/without prefix)
- `normalizers/enums.py`: 12+ test cases (every synonym + non-matches)
- `confidence.py`: row aggregate with various missing-field combinations
- `classifier.py`: section-header detection on each sample's headers
- `extractors/deterministic.py`: row extraction on each sample's actor rows
- `pattern_store/db.py`: CRUD + regression validation
- `validators.py`: each validation rule passes/fails as expected

### Synthetic fixtures (`tests/fixtures/synthetic/`)

Generate tiny PDFs via `reportlab` for:
- Single section, 2 actors, all fields present (happy path)
- Missing rate
- Missing phone
- Section header with role keyword + count prefix
- Cancelled row (XXX)
- Composite rate
- Multi-line note

### Ground truth (`tests/fixtures/expected/`)

For each of 5 sample PDFs, a hand-verified `*.expected.csv` with full debug schema. Generation process:
1. Run `bench/generate_ground_truth.py` once (uses Sonnet 4.6).
2. Manually inspect each row, correct errors.
3. Commit frozen.

### VCR cassettes (`tests/fixtures/cassettes/`)

- One cassette per test that hits an LLM.
- Recorded once via `pytest --record-mode=once`.
- Replayed in CI; tests fail if cassette missing.

### Accuracy metrics

```python
def compute_accuracy(expected: list[ExtractedRow],
                     actual: list[ExtractedRow]) -> AccuracyReport:
    """
    Match rows by (document_name, actor_name, role) tuple.
    For each matched row, compute per-field exact match.
    Report:
      - row_recall: matched rows / expected rows
      - row_precision: matched rows / actual rows
      - per_field_accuracy: dict[field_name, float]
      - row_complete: rows where ALL required fields exact match
    """
```

---

## 14. Benchmark Harness

### `bench/run.py`

```bash
python -m bench.run \
    --fixtures tests/fixtures/pdfs \
    --expected tests/fixtures/expected \
    --profiles default best_of_breed cost openai_only \
    --output bench/results/
```

Outputs:
- `bench/results/accuracy.csv` (matrix: profile × sample × field)
- `bench/results/cost.csv` (per profile, per sample, $ amount)
- `bench/results/latency.csv` (p50, p95, p99 per profile)
- `bench/results/dashboard.html` (visual summary)

### `bench/report.py` — HTML dashboard

Templated via jinja2 in `bench/templates/dashboard.html.j2`:

**Components:**
1. **Accuracy heatmap** — profile (rows) × sample (cols), cell = row-complete %. Matplotlib heatmap embedded as base64 PNG.
2. **Cost-vs-accuracy scatter** — x=avg cost per doc, y=avg row-complete %, point per profile.
3. **Per-field bar chart** — grouped bars per field, one group per profile.
4. **Latency distribution** — box plot per profile.
5. **Summary table** — best profile per metric.

Self-contained HTML (CSS inlined, charts as base64 PNG). Open in a browser, no server.

---

## 15. CLI Surface

Built with `typer`. Single entry point: `skins`.

```bash
# Run extraction on a directory of PDFs
skins extract data/input/ --output output/ --profile default

# Run extraction on a single file
skins extract data/input/skins_1.pdf

# Run benchmark
skins bench --profiles default cost --output bench/results/

# Manage pattern store
skins patterns list                              # all patterns, grouped by status
skins patterns list --status pending_review      # filter
skins patterns show <pattern_id>                 # full details + match history
skins patterns approve <pattern_id>              # promote to approved
skins patterns reject <pattern_id> --reason "..."
skins patterns deprecate <pattern_id>

# Re-run regression on existing patterns (e.g., after fixtures change)
skins patterns regress

# Print active config
skins config show
```

---

## 16. Implementation Phases (Build Order)

### Phase 1 — Foundation (must come first)

1. `pyproject.toml` with deps: `pdfplumber`, `pymupdf`, `pydantic`, `typer`, `rapidfuzz`, `duckdb`, `anthropic`, `openai`, `google-genai`, `httpx` (xAI uses OpenAI-compatible), `jinja2`, `matplotlib`, `pyyaml`, `python-dotenv`. Dev deps: `pytest`, `pytest-vcr`, `reportlab`, `ruff`, `mypy`.
2. `Makefile` with: `install`, `test`, `lint`, `typecheck`, `run`, `bench`, `clean`.
3. `src/skins_extractor/__init__.py`
4. `src/skins_extractor/models.py` — Pydantic models (Section 5).
5. `src/skins_extractor/config.py` — load YAML, resolve profile, env merge.
6. `src/skins_extractor/logging_config.py` — structured JSON logs.
7. `src/skins_extractor/cli.py` — Typer scaffold (commands stubbed).

### Phase 2 — Deterministic core

8. `loaders/pdf.py` + `loaders/csv.py` + `loaders/base.py`
9. `fingerprint.py`
10. `segmenter.py` (block grouping by y-coord)
11. `classifier.py` (lexical section detector)
12. `extractors/deterministic.py`
13. `normalizers/{phone, rate, name, enums}.py`
14. `confidence.py`
15. `validators.py`
16. `writers.py`
17. `pipeline.py` — wire it together (LLM stages stubbed)

At end of phase 2: full deterministic-only pipeline runs end-to-end on Skins 3 and produces output. Skins 1/2/4/5 will produce partial output (sections found, but possibly missing fields).

### Phase 3 — LLM integration

18. `llm/provider.py` (Protocol)
19. `llm/anthropic_adapter.py`
20. `llm/openai_adapter.py`
21. `llm/google_adapter.py`
22. `llm/xai_adapter.py`
23. `llm/router.py`
24. `config/prompts/*.md`
25. `extractors/llm_extractor.py` — outline + row-fallback
26. Wire LLM stages into `pipeline.py`

At end of phase 3: full pipeline runs on all 5 samples, all profiles selectable.

### Phase 4 — Pattern store + curation

27. `pattern_store/schema.sql`
28. `pattern_store/db.py`
29. `pattern_store/regression.py`
30. Wire pattern-store lookup into `classifier.py` (between lexical and LLM)
31. Wire LLM-suggested-pattern persistence in `extractors/llm_extractor.py`
32. CLI subcommands `skins patterns list/show/approve/reject/deprecate/regress`
33. `notifications/slack.py` — webhook stub triggered on `pending_review` insert

### Phase 5 — Tests

34. `tests/conftest.py` — fixtures
35. Synthetic PDFs via `reportlab` in `tests/fixtures/synthetic/`
36. Unit tests per module (Section 13)
37. `tests/test_e2e.py` — synthetic + cassette-replay for real fixtures
38. Generate ground truth via `bench/generate_ground_truth.py`, manual review, commit.

### Phase 6 — Benchmark

39. `bench/run.py`
40. `bench/templates/dashboard.html.j2`
41. `bench/report.py` — accuracy/cost/latency matrices + HTML dashboard

### Phase 7 — Polish

42. `README.md` (Section 19 outline)
43. `.env.example`
44. `.gitignore`
45. Sample run output committed: `output/clean.csv`, `output/debug.csv`, `bench/results/dashboard.html`

---

## 17. Dependencies

### `pyproject.toml`

```toml
[project]
name = "skins-extractor"
version = "0.1.0"
description = "PDF roster extraction pipeline"
requires-python = ">=3.12"

dependencies = [
    "pdfplumber>=0.11",
    "pymupdf>=1.24",
    "pydantic>=2.7",
    "typer>=0.12",
    "rapidfuzz>=3.9",
    "duckdb>=1.0",
    "anthropic>=0.39",
    "openai>=1.50",
    "google-genai>=0.1",
    "httpx>=0.27",
    "jinja2>=3.1",
    "matplotlib>=3.9",
    "pyyaml>=6.0",
    "python-dotenv>=1.0",
    "rich>=13",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-vcr>=1.0",
    "reportlab>=4",
    "ruff>=0.5",
    "mypy>=1.10",
]

[project.scripts]
skins = "skins_extractor.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.mypy]
strict = true
python_version = "3.12"
```

---

## 18. Deliverables Checklist

Required by spec:
- [ ] Code repository
- [ ] README with: setup, run, design decisions, productionization notes
- [ ] Sample output CSV (`output/clean.csv` and `output/debug.csv` from running on the 5 samples)

Bonus rubric items:
- [ ] Edge case handling (Section 10)
- [ ] Validation (Section 8 stage 8)
- [ ] Deduplication policy documented (Section 10)
- [ ] Source attribution (`source` column in debug.csv)
- [ ] Logging / debug output (`output/extraction.log`)
- [ ] Failure case explanation (in README + `extraction.log`)

Beyond rubric (architectural completeness):
- [ ] Pattern store with trust-mode config
- [ ] Multi-vendor LLM abstraction (4 adapters)
- [ ] 5 selectable profiles
- [ ] Benchmark harness with HTML dashboard
- [ ] Curator CLI
- [ ] Slack notification stub
- [ ] Color-based cancellation detection
- [ ] OCR fallback chain
- [ ] Composite rate handling
- [ ] Confidence breakdown JSON
- [ ] Test suite with VCR cassettes

---

## 19. Productionization Notes (for README)

The README's "How would you product-ize this?" section should cover:

1. **Deployment shape**: containerize (Dockerfile), schedule via cron / Airflow / Temporal; trigger via S3 event for new PDF uploads.
2. **Pattern store as institutional knowledge**: persist DuckDB outside the container; back up regularly; treat patterns like database migrations.
3. **Curator workflow**: replace CLI with a Slack bot or web UI for the `pending_review` queue. Approval audit trail already in DB.
4. **Format fingerprinting at scale**: extend the fingerprint to cluster docs; dashboard for "top N most-common formats" → focus rule curation effort.
5. **Cost monitoring**: emit metrics per LLM call (provider, model, tokens, $); aggregate into a dashboard; alerts for cost spikes.
6. **Quality monitoring**: emit confidence distribution per run; alert when low-confidence row rate exceeds threshold (signal of new format or model drift).
7. **A/B testing profiles**: shadow-run a candidate profile alongside production; compare extraction outputs; promote when accuracy + cost both improve.
8. **Regression suite**: every new ground-truth CSV added to fixtures gates pattern promotions and benchmark. Treat ground truth like test data — review changes carefully.
9. **Multi-tenant**: per-customer pattern stores; per-customer trust modes (some customers want auto-trust, others mandate human review).
10. **Vendor diversification**: keep all four adapters wired; load-balance or failover at the router layer for resilience.

---

## 20. Known Limitations

Document explicitly in README:

1. **Color detection** depends on PDFs preserving fill/stroke color metadata. PDFs flattened to images won't have this; would need vision LLM or full OCR.
2. **OCR for scanned PDFs** uses vision LLM as last resort; expensive on volume. Production should use Tesseract or a dedicated OCR service for high-volume scanned pipelines.
3. **Composite rate semantics** (e.g., `$224/8 + 250 bump`) emit base only in `rate_amount`. Downstream payroll systems must read `rate_modifiers` to compute final pay.
4. **Cross-document deduplication** is intentionally NOT done — each PDF is a distinct production day. If a use case requires "unique actor list across all docs," that's a downstream analysis tool consuming `clean.csv`, not a pipeline change.
5. **Hand-written notes / annotations** in PDFs are not extracted (would require vision LLM).
6. **Foreign-language PDFs** would need locale-aware enum mappings.
7. **Pattern store regression** uses fixture-set as ground truth; if fixtures don't cover a pattern's intended scope, false-negative regression results are possible.
8. **VCR cassettes** are tied to prompt content. Changing a prompt invalidates cassettes — must re-record (intentional safeguard).

---

## Implementation Order Recap

Build in this order, validate at each stage:

```
Phase 1 (Foundation)
   ↓
Phase 2 (Deterministic core)         ← Run on Skins 3 (CSV) end-to-end
   ↓
Phase 3 (LLM integration)            ← Run on all 5 samples; validate output
   ↓
Phase 4 (Pattern store + curation)   ← Run twice; verify second run uses cached patterns
   ↓
Phase 5 (Tests + ground truth)       ← Lock in regression suite
   ↓
Phase 6 (Benchmark)                  ← Generate dashboard
   ↓
Phase 7 (Polish + README)            ← Ship
```

End of plan.
