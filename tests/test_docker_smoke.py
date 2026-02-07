from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_COMPOSE_BASE = [
    "docker",
    "compose",
    "-f",
    "docker-compose.yml",
    "-f",
    "docker-compose.override.dev.yml",
]
_ENV_FILE_TEMPLATE = """\
TELEGRAM_BOT_TOKEN=example
STORAGE_GOOGLE_DRIVE_ALL_ACCESSIBLE=true
SMOKE_TEST_SECONDS={seconds}
"""


def _docker_available() -> bool:
    try:
        subprocess.run(
            ["docker", "info"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return False
    return True


def _run(cmd: list[str], *, cwd: Path, timeout: int = 300) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, timeout=timeout)


def _wait_for_health(project: str, service: str, url: str) -> None:
    deadline = time.time() + 60
    cmd = [*_COMPOSE_BASE, "-p", project, "exec", "-T", service, "wget", "-qO-", url]
    while time.time() < deadline:
        try:
            _run(cmd, cwd=_ROOT, timeout=20)
            return
        except subprocess.SubprocessError:
            time.sleep(2)
    raise AssertionError(f"{service} did not become healthy")


@pytest.mark.integration
def test_docker_smoke_bot_and_ingest() -> None:
    if not _docker_available():
        pytest.skip("Docker unavailable")

    project = f"smoke-{uuid4().hex[:8]}"
    seconds = 20

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        google_sa_path = tmpdir_path / "google_sa.json"
        google_sa_path.write_text(json.dumps({}, indent=2))
        os.environ["GOOGLE_SA_FILE"] = str(google_sa_path)

        env_path = tmpdir_path / ".env"
        env_path.write_text(_ENV_FILE_TEMPLATE.format(seconds=seconds))
        os.environ["ENV_FILE"] = str(env_path)

        cmd = [*_COMPOSE_BASE, "-p", project]

        try:
            _run([*cmd, "up", "-d", "--build", "--wait"], cwd=_ROOT, timeout=900)
            _wait_for_health(project, "bot", "http://localhost:8080/healthz")
            _wait_for_health(project, "ingest", "http://localhost:8081/healthz")
        finally:
            _run([*cmd, "down", "-v", "--remove-orphans"], cwd=_ROOT, timeout=300)
