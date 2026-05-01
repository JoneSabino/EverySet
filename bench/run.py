"""Benchmark harness — runs extraction across profiles and fixtures."""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

import typer

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from skins_extractor.config import load_config
from skins_extractor.extractors.llm_extractor import LLMExtractor
from skins_extractor.llm.router import LLMRouter
from skins_extractor.pipeline import run_pipeline
from skins_extractor.models import ExtractedRow

app = typer.Typer()

PROFILES = ["default", "cost", "openai_only", "best_of_breed", "high_accuracy"]


def compute_accuracy(
    expected: list[dict],
    actual: list[ExtractedRow],
) -> dict:
    """Match rows and compute per-field accuracy."""
    matched = 0
    total_expected = len(expected)
    total_actual = len(actual)

    field_correct: dict[str, int] = {
        f: 0 for f in ("actor_name", "phone", "email", "role_type", "role", "call_time")
    }

    for exp in expected:
        exp_name = exp.get("actor_name", "").lower()
        match = next(
            (r for r in actual if r.actor_name.lower() == exp_name),
            None,
        )
        if match:
            matched += 1
            for field in field_correct:
                exp_val = str(exp.get(field, "")).strip().lower()
                act_val = str(getattr(match, field, "")).strip().lower()
                if exp_val == act_val:
                    field_correct[field] += 1

    row_recall = matched / total_expected if total_expected else 0.0
    row_precision = matched / total_actual if total_actual else 0.0

    return {
        "row_recall": row_recall,
        "row_precision": row_precision,
        "matched": matched,
        "total_expected": total_expected,
        "total_actual": total_actual,
        **{f"field_{k}_accuracy": v / matched if matched else 0.0 for k, v in field_correct.items()},
    }


@app.command()
def main(
    fixtures: str = typer.Option("tests/fixtures/pdfs"),
    expected: str = typer.Option("tests/fixtures/expected"),
    output: str = typer.Option("bench/results/"),
    profiles: list[str] = typer.Option(default=["default"]),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip LLM calls (deterministic only)"),
) -> None:
    """Run benchmark across profiles."""
    out_dir = Path(output)
    out_dir.mkdir(parents=True, exist_ok=True)

    fixtures_dir = Path(fixtures)
    expected_dir = Path(expected)

    pdf_files = sorted(fixtures_dir.glob("*.pdf")) + sorted(fixtures_dir.glob("*.csv"))

    results: list[dict] = []

    for profile_name in profiles:
        try:
            config = load_config(profile_name)
        except Exception as e:
            print(f"Skipping profile {profile_name}: {e}")
            continue

        llm_extractor = None
        if not no_llm:
            try:
                router = LLMRouter(config.profile)
                llm_extractor = LLMExtractor(router=router)
            except Exception as e:
                print(f"LLM unavailable ({e}) — running deterministic only")

        for pdf_path in pdf_files:
            expected_csv = expected_dir / f"{pdf_path.stem}.expected.csv"
            exp_rows: list[dict] = []
            if expected_csv.exists():
                with open(expected_csv, newline="") as f:
                    exp_rows = list(csv.DictReader(f))

            t0 = time.perf_counter()
            try:
                rows = run_pipeline(pdf_path, config, llm_extractor=llm_extractor)
                elapsed = time.perf_counter() - t0
                acc = compute_accuracy(exp_rows, rows) if exp_rows else {}
                results.append({
                    "profile": profile_name,
                    "document": pdf_path.name,
                    "rows_extracted": len(rows),
                    "elapsed_s": round(elapsed, 2),
                    **acc,
                })
            except Exception as e:
                print(f"  ERROR on {pdf_path.name}: {e}")
                results.append({
                    "profile": profile_name,
                    "document": pdf_path.name,
                    "error": str(e),
                })

    # Write accuracy CSV
    if results:
        all_keys = set()
        for r in results:
            all_keys.update(r.keys())
        sorted_keys = sorted(all_keys)
        with open(out_dir / "accuracy.csv", "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=sorted_keys)
            writer.writeheader()
            writer.writerows(results)
        print(f"Benchmark results written to {out_dir / 'accuracy.csv'}")

    # Generate HTML dashboard
    try:
        from bench.report import generate_report
        generate_report(results, str(out_dir / "dashboard.html"))
        print(f"Dashboard written to {out_dir / 'dashboard.html'}")
    except Exception as e:
        print(f"Dashboard generation failed: {e}")


if __name__ == "__main__":
    app()
