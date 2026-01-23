# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Plumbline is a local-first portfolio policy engine for investment management. It provides a web dashboard for defining investment policies, contribution allocation ("I have X EUR—what should I buy?"), and reproducible policy backtests with cost modeling.

**MVP is read-only**: it generates proposals and reports; it does not place trades.

## Golden Rules (must follow)

1) **No business logic in routes/templates.** Routes call application use-cases only.
2) **Domain is pure Python.** `app/domain` must not import FastAPI, SQLAlchemy, or anything from `app/api`, `app/web`, or `app/infrastructure`.
3) **Determinism is mandatory** for allocator/backtest: stable ordering, no `datetime.now()` in algorithms, record hashes/inputs.
4) **Do not add live trading or brokerage credentials** in MVP.
5) Keep solutions **simple and auditable** (KISS, DRY, SOLID—pragmatic).

## Commands

```bash
# Install dependencies
make install          # or: uv sync

# Run development server (port 8005)
make dev              # or: uv run uvicorn app.main:app --reload --port 8005

# Run all checks (format, lint, typecheck, test)
make all

# Individual commands
uv run ruff format .           # Format code
uv run ruff check . --fix      # Lint with auto-fix
uv run mypy app                # Type check
uv run pytest                  # Run all tests
uv run pytest tests/api/routes/test_utils.py::test_health_check_returns_ok  # Single test
```

## Architecture (DDD-lite, not full enterprise DDD)

**Top-level structure in `app/`:**
- `core/` - settings, logging, shared utilities (no business logic)
- `api/` - JSON API routes (prefixed with /api/v1)
- `web/` - HTML pages (Jinja2 + HTMX) served at /
- `domain/` - pure business rules + domain models (policy, allocator, backtest, costs, metrics)
- `application/` - use-cases that orchestrate domain + infrastructure
- `infrastructure/` - DB models/repositories, CSV importers, external providers

**DDD-lite policy:**
- Put only the following into `domain/`: policy parsing/validation, drift/allocator, costs, backtest simulation, metrics.
- CSV parsing and persistence belong in `infrastructure/`.
- Use-cases live in `application/` (one file per use-case).
- Avoid over-abstracting repositories/interfaces unless needed (keep it lightweight).

**Entry points:**
- `app/main.py` - creates FastAPI app, mounts templates/static, includes routers.

## Coding Standards

- Prefer small pure functions for core logic.
- Use OOP lightly:
  - Pydantic models for DTOs/config
  - small repository helpers (functions or thin classes)
  - avoid deep inheritance hierarchies
- Add docstrings only when they add real value (explain assumptions). Do not add one-line file docstrings.
- Keep code explicit and readable; avoid “magic” globals.

## Testing Standards (pytest)

- Use pytest with tests as functions, not unittest classes.
- Tests should mirror structure where practical: `tests/domain/`, `tests/application/`, `tests/web/`.

**Mandatory tests for allocator:**
- sum(allocations) equals contribution (within epsilon)
- allocations only in allowed universe (core-only vs satellite)
- respects `min_trade_value` behavior
- respects `max_position_weight` behavior (document tolerance)

**Mandatory tests for backtest:**
- determinism: same policy + same data + same schedule => identical metrics and identical curve hash
- costs are applied consistently

**Determinism Rules:**
- Sort tickers consistently and iterate in stable order.
- No now() or current time inside algorithmic functions.
- Every proposal/backtest run must store:
  - policy hash
  - data range
  - contribution schedule inputs
  - version identifiers (as available)

## Error Handling

- Validate early in `application/` and `domain/`.
- Raise typed exceptions from `domain/` and `application/`:
  - `ValidationError`, `PolicyError`, `DataMissingError`
- Web layer catches exceptions and renders user-friendly errors (no stack traces to users).

## Definition of Done (for each task)
- `make all` passes
- Any non-trivial logic includes tests
- Routes/templates remain thin (no logic leakage)
- Feature meets acceptance criteria in TASK card
- Summarize changes in the task card/PR description

## Conventions

- **Branch naming:** `{type}/description` where type is one of: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `ci`
- **Commits:** Conventional commits enforced via commitizen
- **Python:** 3.13+, strict mypy, ruff for linting/formatting
- **Line length:** 120 characters
