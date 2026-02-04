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
	.venv/bin/ruff check --fix

fmt:
	.venv/bin/ruff format

test:
	.venv/bin/pytest
