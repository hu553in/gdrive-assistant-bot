from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_BASE = [
    "docker",
    "compose",
    "-f",
    "docker-compose.yml",
    "-f",
    "docker-compose.override.dev.yml",
]


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
    cmd = [*COMPOSE_BASE, "-p", project, "exec", "-T", service, "wget", "-qO-", url]
    while time.time() < deadline:
        try:
            _run(cmd, cwd=ROOT, timeout=20)
            return
        except subprocess.SubprocessError:
            time.sleep(2)
    raise AssertionError(f"{service} did not become healthy")


@pytest.mark.integration
def test_docker_smoke_bot_and_ingest() -> None:
    if not _docker_available():
        pytest.skip("Docker unavailable")

    project = f"smoke-{uuid4().hex[:8]}"
    smoke_seconds = 20

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        override = {
            "services": {
                "bot": {"environment": {"SMOKE_TEST_SECONDS": str(smoke_seconds)}},
                "ingest": {"environment": {"SMOKE_TEST_SECONDS": str(smoke_seconds)}},
            },
            "secrets": {"google_sa": {"file": str(tmpdir_path / "google_sa.json")}},
        }

        override_path = tmpdir_path / "docker-compose.smoke.yml"
        override_path.write_text(json.dumps(override, indent=2))

        secrets_path = tmpdir_path / "google_sa.json"
        secrets_path.write_text(json.dumps({}, indent=2))

        cmd = [*COMPOSE_BASE, "-p", project, "-f", str(override_path)]

        try:
            _run([*cmd, "up", "-d", "--build"], cwd=ROOT, timeout=900)
            _wait_for_health(project, "bot", "http://localhost:8080/healthz")
            _wait_for_health(project, "ingest", "http://localhost:8081/healthz")
        finally:
            _run([*cmd, "down", "-v", "--remove-orphans"], cwd=ROOT, timeout=300)
