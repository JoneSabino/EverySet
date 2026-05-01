.PHONY: install format lint typecheck test check run bench clean

install:
	uv sync

format:
	uv run ruff format src/ tests/

lint:
	uv run ruff check --fix src/ tests/

typecheck:
	uv run pyright src/

test:
	uv run pytest tests/ -v

check: format lint typecheck test

run:
	set -a && . .env && set +a && uv run skins extract ../ai-take-home-assessment/skins-report-samples/

bench:
	uv run python -m bench.run --fixtures tests/fixtures/pdfs --expected tests/fixtures/expected --output bench/results/

clean:
	rm -rf output/*.csv output/*.log bench/results/ data/patterns.duckdb __pycache__ .ruff_cache .mypy_cache
