SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -euo pipefail -c

COMPOSE_FILES ?= -f docker-compose.yml -f docker-compose.override.dev.yml

ensure_env:
	if [ ! -f .env ]; then cp .env.example .env; fi

install_deps:
	uv sync --frozen --no-install-project

sync_deps:
	uv sync

check_deps_updates:
	uv tree --outdated --depth=1 | grep latest

check_deps_vuln:
	uv run pysentry-rs .

start: ensure_env
	docker compose $(COMPOSE_FILES) \
	up -d --build --wait --remove-orphans

stop: ensure_env
	docker compose $(COMPOSE_FILES) \
	down --remove-orphans

restart: stop start

lint:
	uv run ruff format
	uv run ruff check --fix

test:
	uv run pytest

check_types:
	uv run ty check .

check:
	uv run prek --all-files --hook-stage pre-commit

logs_bot:
	docker compose $(COMPOSE_FILES) logs -f bot

logs_ingest:
	docker compose $(COMPOSE_FILES) logs -f ingest
