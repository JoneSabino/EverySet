"""Skins Extractor CLI."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="skins",
    help="PDF roster extraction pipeline for Skins call sheets.",
    add_completion=False,
)
patterns_app = typer.Typer(help="Manage the pattern store.")
app.add_typer(patterns_app, name="patterns")

console = Console()


def _get_config(profile: str | None) -> object:
    from .config import load_config

    return load_config(profile)


def _get_pattern_store(config: object) -> object:
    from .config import AppConfig
    from .pattern_store.db import PatternStore

    cfg: AppConfig = config  # type: ignore[assignment]
    return PatternStore(cfg.pipeline.pattern_store_path)


@app.command("extract")
def extract(
    input_path: Annotated[str, typer.Argument(help="PDF/CSV file or directory of PDFs")],
    output: Annotated[str | None, typer.Option(help="Output directory")] = None,
    profile: Annotated[str | None, typer.Option(help="LLM profile to use")] = None,
    no_llm: Annotated[bool, typer.Option("--no-llm", help="Skip LLM calls")] = False,
    auto_approve: Annotated[
        bool,
        typer.Option(
            "--auto-approve", help="Auto-approve LLM-proposed patterns (skip human review queue)"
        ),
    ] = False,
) -> None:
    """Extract roster data from PDF/CSV files."""
    from .config import AppConfig, load_config
    from .logging_config import setup_logging
    from .pipeline import process_directory, run_pipeline
    from .writers import write_clean_csv, write_debug_csv

    config: AppConfig = load_config(profile)  # type: ignore[assignment]

    if output:
        config.output.clean_csv = str(Path(output) / "clean.csv")
        config.output.debug_csv = str(Path(output) / "debug.csv")
        config.output.log_file = str(Path(output) / "extraction.log")

    if auto_approve:
        config.pipeline.trust_mode = "auto_approve"

    setup_logging(config.pipeline.log_level, config.output.log_file)

    # Build LLM extractor unless --no-llm
    llm_extractor = None
    if not no_llm:
        try:
            from .extractors.llm_extractor import LLMExtractor
            from .llm.router import LLMRouter

            router = LLMRouter(config.profile)
            llm_extractor = LLMExtractor(router=router)
        except Exception as e:
            console.print(f"[yellow]LLM unavailable ({e}) — running deterministic only[/yellow]")

    # Wire pattern store so approved patterns are reused and new ones are saved
    pattern_store = None
    try:
        pattern_store = _get_pattern_store(config)
    except Exception as e:
        console.print(
            f"[yellow]Pattern store unavailable ({e}) — patterns will not be saved[/yellow]"
        )

    p = Path(input_path)
    if p.is_dir():
        from .pipeline import process_directory

        rows = process_directory(p, config, llm_extractor, pattern_store)
    else:
        from .pipeline import run_pipeline
        from .writers import write_clean_csv, write_debug_csv

        rows = run_pipeline(p, config, llm_extractor, pattern_store)
        write_clean_csv(rows, config.output.clean_csv)
        write_debug_csv(rows, config.output.debug_csv)

    console.print(f"[green]Extracted {len(rows)} rows[/green]")
    console.print(f"  clean: {config.output.clean_csv}")
    console.print(f"  debug: {config.output.debug_csv}")


@app.command("bench")
def bench(
    profiles: Annotated[list[str] | None, typer.Option(help="Profiles to benchmark")] = None,
    fixtures: Annotated[str, typer.Option()] = "tests/fixtures/pdfs",
    expected: Annotated[str, typer.Option()] = "tests/fixtures/expected",
    output: Annotated[str, typer.Option()] = "bench/results/",
) -> None:
    """Run benchmark against all profiles."""
    import subprocess

    cmd = [
        sys.executable,
        "-m",
        "bench.run",
        "--fixtures",
        fixtures,
        "--expected",
        expected,
        "--output",
        output,
    ]
    if profiles:
        cmd += ["--profiles"] + profiles
    subprocess.run(cmd, check=False)


@app.command("config")
def show_config(
    profile: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Show active configuration."""
    from .config import load_config

    config = load_config(profile)
    console.print_json(config.model_dump_json(indent=2))


# ── pattern subcommands ───────────────────────────────────────────────────────


@patterns_app.command("list")
def patterns_list(
    status: Annotated[str | None, typer.Option()] = None,
    profile: Annotated[str | None, typer.Option()] = None,
) -> None:
    """List patterns in the store."""
    config = _get_config(profile)
    store = _get_pattern_store(config)
    from .pattern_store.db import PatternStore

    ps: PatternStore = store  # type: ignore[assignment]
    patterns = ps.list_all(status)

    table = Table(title=f"Patterns ({status or 'all'})")
    table.add_column("ID (prefix)", style="cyan")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Fingerprint")
    table.add_column("Description")
    for p in patterns:
        table.add_row(
            p.pattern_id[:8],
            p.pattern_type,
            p.status,
            p.format_fingerprint,
            (p.description or "")[:50],
        )
    console.print(table)


@patterns_app.command("show")
def patterns_show(pattern_id: str) -> None:
    """Show full details of a pattern."""

    config = _get_config(None)
    store = _get_pattern_store(config)
    from .pattern_store.db import PatternStore

    ps: PatternStore = store  # type: ignore[assignment]
    p = ps.get(pattern_id) or next(
        (x for x in ps.list_all() if x.pattern_id.startswith(pattern_id)), None
    )
    if p is None:
        console.print(f"[red]Pattern {pattern_id!r} not found[/red]")
        raise typer.Exit(1)
    console.print_json(p.model_dump_json(indent=2))


@patterns_app.command("approve")
def patterns_approve(pattern_id: str, approver: str = "human") -> None:
    """Promote a pattern to approved status."""
    config = _get_config(None)
    store = _get_pattern_store(config)
    from .pattern_store.db import PatternStore

    ps: PatternStore = store  # type: ignore[assignment]
    ps.approve(pattern_id, approver)
    console.print(f"[green]Approved {pattern_id[:8]}[/green]")


@patterns_app.command("reject")
def patterns_reject(
    pattern_id: str,
    reason: Annotated[str, typer.Option()] = "",
) -> None:
    """Reject a pattern."""
    config = _get_config(None)
    store = _get_pattern_store(config)
    from .pattern_store.db import PatternStore

    ps: PatternStore = store  # type: ignore[assignment]
    ps.reject(pattern_id, reason)
    console.print(f"[yellow]Rejected {pattern_id[:8]}[/yellow]")


@patterns_app.command("deprecate")
def patterns_deprecate(pattern_id: str) -> None:
    """Deprecate a pattern."""
    config = _get_config(None)
    store = _get_pattern_store(config)
    from .pattern_store.db import PatternStore

    ps: PatternStore = store  # type: ignore[assignment]
    ps.deprecate(pattern_id)
    console.print(f"[dim]Deprecated {pattern_id[:8]}[/dim]")


@patterns_app.command("regress")
def patterns_regress(
    fixtures: Annotated[str, typer.Option()] = "tests/fixtures/expected",
) -> None:
    """Run regression validation on all pending patterns."""
    config = _get_config(None)
    store = _get_pattern_store(config)
    from .pattern_store.db import PatternStore
    from .pattern_store.regression import run_regression

    ps: PatternStore = store  # type: ignore[assignment]
    pending = ps.list_pending()
    if not pending:
        console.print("No pending patterns.")
        return
    for p in pending:
        passes, precision = run_regression(p, fixtures)
        status = "[green]PASS[/green]" if passes else "[red]FAIL[/red]"
        console.print(f"  {p.pattern_id[:8]} {status} precision={precision:.2f}")


if __name__ == "__main__":
    app()
