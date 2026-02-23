SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -euo pipefail -c

COMPOSE_FILES ?= -f docker-compose.yml -f docker-compose.override.dev.yml

.PHONY: ensure_env
ensure_env:
	if [ ! -f .env ]; then cp .env.example .env; fi

.PHONY: install_deps
install_deps:
	uv sync --frozen --no-install-project

.PHONY: sync_deps
sync_deps:
	uv sync

.PHONY: check_deps_updates
check_deps_updates:
	uv tree --outdated --depth=1 | grep latest

.PHONY: check_deps_vuln
check_deps_vuln:
	uv run pysentry-rs .

.PHONY: start
start: ensure_env
	docker compose $(COMPOSE_FILES) \
	up -d --build --wait --remove-orphans

.PHONY: stop
stop: ensure_env
	docker compose $(COMPOSE_FILES) \
	down --remove-orphans

.PHONY: restart
restart: stop start

.PHONY: lint
lint:
	uv run ruff format
	uv run ruff check --fix

.PHONY: test
test:
	uv run pytest

.PHONY: check_types
check_types:
	uv run ty check .

.PHONY: check
check:
	uv run prek --all-files --hook-stage pre-commit

.PHONY: logs_bot
logs_bot:
	docker compose $(COMPOSE_FILES) logs -f bot

.PHONY: logs_ingest
logs_ingest:
	docker compose $(COMPOSE_FILES) logs -f ingest
