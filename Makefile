# PolicyGround task runner (spec 00 A1: dev, test, eval, up, down).
#
# NOTE: `make` is not installed on the Windows machine this repo was built on (BLOCKERS.md B3).
# `make.ps1` exposes the identical target names and is the path the README quickstart shows first.
# This file is the CI and Linux/macOS entry point.

.DEFAULT_GOAL := help
.PHONY: help install ingest dev api web test lint typecheck eval eval-offline check up down clean

PY := uv run

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Sync Python deps (uv) and frontend deps (npm)
	uv sync --extra dev
	cd frontend && npm install

ingest: ## Rebuild the retrieval index from corpus/ (one command, spec 08 F2)
	$(PY) pg ingest --rebuild

dev: ## Full local demo: ingest, then API + SPA together
	$(MAKE) ingest
	$(PY) pg serve & cd frontend && npm run dev

api: ## Backend only, http://localhost:8000
	$(PY) pg serve

web: ## Frontend only, http://localhost:5173
	cd frontend && npm run dev

test: ## Unit tests (LLM mocked; `live`-marked tests deselected)
	$(PY) pytest tests -m "not live and not azure"

lint: ## ruff
	$(PY) ruff check backend/src tests evals
	$(PY) ruff format --check backend/src tests evals

typecheck: ## mypy (strict)
	$(PY) mypy

eval: ## Groundedness suite + all four gates
	$(PY) pytest evals -m "not live and not azure"

eval-offline: ## Same, with judge pinned to cache-only (a cache miss is fatal)
	OFFLINE=1 $(PY) pytest evals -m "not live and not azure"

check: lint typecheck test eval ## Everything CI runs

up: ## docker compose up (Postgres + api + web)
	docker compose up -d

down: ## docker compose down
	docker compose down -v

clean: ## Remove generated indexes and the dev database
	rm -rf data/ .pytest_cache .ruff_cache .mypy_cache
