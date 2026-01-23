# Plumbline

Local-first portfolio policy engine with auditable contribution plans & reproducible policy backtests.

## Features

- **Investment policies** — Define target weights, constraints, and drift thresholds in YAML
- **Contribution allocator** — Answer "I have X EUR—what should I buy?" with a transparent, auditable plan
- **Reproducible backtests** — Simulate policies over historical data with cost modeling
- **Currency insights** — Track currency exposure and FX attribution

## Quick Start

```bash
# Install dependencies
make install

# Configure environment
cp .env.example .env
# Edit .env with your PROJECT_NAME

# Run development server
make dev
```

Open http://localhost:8005

## Requirements

- Python 3.13+
- [uv](https://github.com/astral-sh/uv)

## Development

```bash
# Run all checks (format, lint, typecheck, test)
make all

# Individual commands
uv run pytest                  # Run tests
uv run mypy app                # Type check
uv run ruff check . --fix      # Lint
```

See [CLAUDE.md](CLAUDE.md) for architecture and coding standards.

## Status

MVP in development — read-only proposals and reports, no live trading.

See [docs/OVERVIEW.md](docs/OVERVIEW.md) for project scope and [docs/REQUIREMENTS_FUNCTIONAL.md](docs/REQUIREMENTS_FUNCTIONAL.md) for detailed requirements.
