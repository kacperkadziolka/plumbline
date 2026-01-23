.PHONY: install dev all

install:
	uv sync

dev:
	uv run uvicorn app.main:app --reload --port 8005

all:
	uv run ruff format .
	uv run ruff check . --fix
	uv run mypy app
	uv run pytest
