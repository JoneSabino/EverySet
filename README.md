# Skins Extractor

[![CI](https://github.com/JoneSabino/EverySet/actions/workflows/ci.yml/badge.svg)](https://github.com/JoneSabino/EverySet/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

PDF roster extraction pipeline for EverySet "Skins" call sheets. Extracts structured actor data from multi-column PDF exports and CSV rosters into two normalized CSVs.

## Output Schema

| Field | Description |
|---|---|
| `document_name` | Source filename |
| `call_time` | Actor call time |
| `union_name` | Union status (union / non-union / sag-aftra) |
| `actor_name` | Full name |
| `role_type` | Canonical role type (stand-in, background, photo double, …) |
| `role` | Freeform role description from the section header |
| `rate` | Raw rate string (e.g. `$262/8`) |
| `phone` | Normalized phone |
| `confidence` | Aggregate confidence score (0.0–1.0) |

Two output files:
- **`clean.csv`** — import-ready rows, cancelled actors (XXX) excluded
- **`debug.csv`** — full superset including cancelled rows, per-field confidence, extraction method, and source block text

## Quick Start

**Prerequisites**: Python 3.12+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
# Install uv (if you don't have it)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install
git clone https://github.com/JoneSabino/EverySet.git
cd EverySet
uv sync

# Configure API key
cp .env.example .env   # set ANTHROPIC_API_KEY in .env

# Run
make run

# Results
open output/clean.csv
```

## CLI Reference

### `skins extract`

```
skins extract [OPTIONS] INPUT_PATH
```

| Argument / Option | Description |
|---|---|
| `INPUT_PATH` | PDF/CSV file or directory of PDFs (required) |
| `--output TEXT` | Output directory (default: `output/`) |
| `--profile TEXT` | LLM profile to use (default: `default`) |
| `--no-llm` | Skip all LLM calls — deterministic extraction only |
| `--auto-approve` | Auto-approve LLM-proposed patterns (skip human review queue) |

### `skins config`

```
skins config [--profile TEXT]
```

Prints the resolved configuration for the given profile.

### `skins patterns`

```
skins patterns list
skins patterns show <pattern_id>
skins patterns approve <pattern_id>
skins patterns reject <pattern_id>
skins patterns deprecate <pattern_id>
skins patterns regress
```

Manage the pattern store — review, approve, or reject LLM-generated patterns before they are re-used on future documents.

### `skins bench`

```
skins bench [--profiles TEXT] [--fixtures TEXT] [--expected TEXT] [--output TEXT]
```

Run extraction benchmark against all (or selected) profiles and compare to expected fixtures.

### LLM Profiles

| Profile | Outliner | Row fallback | Use case |
|---|---|---|---|
| `default` | Claude Sonnet 4.6 | Claude Haiku 4.5 | Best balance — single API key |
| `best_of_breed` | GPT-4o | Gemini 2.5 Flash Lite | Multi-provider, best price/quality |
| `cost` | Grok 3 Fast | Grok 3 Fast | Cheapest option |
| `openai_only` | GPT-4o | GPT-4o Mini | OpenAI-only environments |
| `high_accuracy` | Claude Opus 4.7 | GPT-4o | Maximum quality |

## Testing

```bash
make test        # uv run pytest tests/ -v
make check       # format + lint + typecheck + test
```

## Learning Loop

The pipeline learns from each document it processes. When the LLM is called to handle an unrecognized format, it proposes extraction patterns alongside its output. Those patterns are saved to the pattern store and — once approved — are applied automatically on subsequent documents with the same format fingerprint. Over time, LLM call rate drops toward zero for repeat formats.

### Two modes

| Mode | How to enable | Behavior |
|---|---|---|
| `human_approval` (default) | Default config | LLM-proposed patterns land in `pending_review`. A curator reviews and approves before they are used. |
| `auto_approve` | `--auto-approve` flag or `trust_mode: auto_approve` in `profiles.yaml` | Patterns are inserted as `approved` immediately. No human review step. Use for trusted, high-volume pipelines. |

### Pattern lifecycle

```
pending_review → approved → [used on all matching fingerprints] → deprecated
                → rejected
```

### Human-approval workflow

```bash
# After running extraction, check what the LLM proposed
skins patterns list

# Inspect a pattern before approving
skins patterns show <id>

# Run the regression suite to validate it doesn't break existing fixtures
skins patterns regress

# Approve — pattern will be reused on the next run with the same format fingerprint
skins patterns approve <id>

# Or discard
skins patterns reject <id> --reason "too broad"
```

### Auto-approve mode

```bash
# Approve all LLM-proposed patterns immediately
skins extract input/ --auto-approve
```

Use `auto_approve` when you have high confidence in the LLM's proposals (e.g. in a controlled environment with well-known document formats). For production, `human_approval` is safer — the curator acts as a quality gate before patterns reach all future extractions.

## Design Decisions

**Deterministic-first, LLM as fallback** — extraction runs in four layers: regex/fuzzy → pattern store → LLM document outline → LLM per-row fallback. LLM is only called when determinism fails, keeping cost and latency low on repeat formats.

**Format fingerprinting + pattern store** — each document is fingerprinted by structure. Approved LLM-generated patterns are stored in DuckDB and re-used on future documents with the same fingerprint, driving LLM call rate toward zero over time.

**Per-field confidence, not just per-row** — confidence is computed per field based on extraction method, then aggregated into a row score with required fields weighted 3×. A row missing its actor name cannot score above 0.5 regardless of other fields.

**Multi-column PDF handling** — the loader detects column boundaries via x0-distribution gap analysis and processes each column independently, preventing actor names from merging with rate strings on the same line.

**Multi-provider LLM with swappable profiles** — outliner and row-fallback models are configured independently per profile (`default`, `cost`, `high_accuracy`, etc.), allowing cost/quality tradeoffs without code changes.

## Productionization Notes

**Infrastructure**

The pipeline is single-threaded and processes one file at a time. At production volume, files should be enqueued (SQS, Celery) and processed by a pool of workers. Each worker runs the full pipeline independently — the only shared state is the pattern store.

The pattern store (DuckDB) works well for a single writer, but breaks under concurrent writes from multiple workers. Migrating to Postgres with a lightweight API layer (or a single dedicated pattern-store worker) is the right call before scaling out. The schema and approval logic are already cleanly separated, so the migration is mechanical.

Containerize with Docker and trigger on S3 `ObjectCreated` events. The pattern store should live on persistent storage external to the container (RDS, EFS), not baked into the image.

**Curator workflow**

The `pending_review` queue in the pattern store is the main human touchpoint. Replace the CLI with a Slack bot or internal web UI — when a new format fingerprint appears, the curator sees a card with the raw block text, the LLM-proposed extraction, and approve/reject buttons. Approved patterns are re-used on all future documents with the same fingerprint, eliminating LLM cost on repeat formats.

Run `skins patterns regress` in CI before deploying pattern store changes to catch regressions before they reach production.

**Observability**

Two signals to monitor per batch:

- **LLM call rate**: a spike means new unrecognized formats are entering the pipeline. Alert the curator.
- **Low-confidence row fraction**: if more than ~15% of rows score below 0.60, either the format changed or the model drifted. Both require curator review.

The debug CSV captures extraction method and confidence per row — these are the raw inputs for both metrics. In production, emit them as structured events (DataDog, CloudWatch) instead of writing a CSV.

**Model and prompt changes**

LLM providers update models on their own schedule. Pin model IDs explicitly (already done in `profiles.yaml`) and run the benchmark suite (`make bench`) against a frozen fixture set before promoting any model or prompt change to production.

## Next Steps

1. **Ground-truth accuracy measurement**: no expected fixture CSVs exist yet, so precision/recall against known-good outputs has not been measured. The `bench` infrastructure (`make bench`, `skins bench`) is in place — the missing piece is populating `tests/fixtures/expected/` with verified CSVs for each sample PDF and wiring field-level diff metrics (name match, phone match, role match) into the report.

2. **Token and cost tracking**: LLM `response.usage` (input/output token counts) is returned by every provider but currently discarded in the adapter layer. Capturing it per call and accumulating in `ExtractionRun` would unlock cost-per-document reporting, LLM spend trends, and alerts when a new document format causes a spike — all from the same DuckDB store that already records runs.

3. **Scanned PDFs**: the pipeline detects low-text PDFs and falls back to vision LLM. For high-volume scanned input, replace this with a dedicated OCR step (AWS Textract, Google Document AI) before extraction — cheaper and faster at scale.

4. **Composite rate parsing**: rates like `$224/8 + $250 bump` are stored split across `rate_amount` and `rate_modifiers`. A structured rate parser would normalize these into a single canonical format for downstream payroll systems.

5. **Color-based cancellation on flattened PDFs**: currently relies on fill color metadata. For PDFs without color metadata, trigger the vision LLM fallback specifically for cancellation detection.

6. **Multi-column layout robustness**: the column split heuristic handles standard layouts well. Non-standard or densely packed PDFs could benefit from LLM-assisted layout parsing as a fallback.
