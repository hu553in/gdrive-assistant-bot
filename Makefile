SHELL := /usr/bin/env bash
.ONESHELL:
.SHELLFLAGS := -euo pipefail -c

COMPOSE_FILES ?= -f docker-compose.yml -f docker-compose.override.dev.yml

ensure_env:
	if [ ! -f .env ]; then cp .env.example .env; fi

install_deps:
	uv tool install pre-commit
	uv tool install ruff
	uv sync --frozen --no-install-project

sync_deps:
	uv sync

check_deps_updates:
	uv tree --outdated --depth=1 | grep latest

check_deps_vuln:
	uvx pysentry-rs --sources pypa,pypi,osv --fail-on low .

start: ensure_env
	docker compose $(COMPOSE_FILES) \
	up -d --build --wait --remove-orphans

stop: ensure_env
	docker compose $(COMPOSE_FILES) \
	down --remove-orphans

restart: stop start

lint:
	ruff check --fix

fmt:
	ruff format
