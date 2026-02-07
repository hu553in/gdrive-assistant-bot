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
	.venv/bin/pysentry-rs --sources pypa,pypi,osv --fail-on low .

start: ensure_env
	docker compose $(COMPOSE_FILES) \
	up -d --build --wait --remove-orphans

stop: ensure_env
	docker compose $(COMPOSE_FILES) \
	down --remove-orphans

restart: stop start

lint:
	.venv/bin/ruff format
	.venv/bin/ruff check --fix

test:
	.venv/bin/pytest

check_types:
    # always exit with 0 until all existing type errors are fixed
	.venv/bin/ty check --exit-zero .

check:
	.venv/bin/prek --all-files --hook-stage pre-commit

logs_bot:
	docker compose $(COMPOSE_FILES) logs -f bot

logs_ingest:
	docker compose $(COMPOSE_FILES) logs -f ingest
