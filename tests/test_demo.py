"""A plain laptop can preview without official assets, credentials or CANN."""

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from fastapi.testclient import TestClient

from aworker.lab.dashboard import create_demo_app


# ---- preview assets and explicitly unavailable real controls -----------------
def test_demo_serves_same_assets_without_any_execution_api(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with TestClient(create_demo_app()) as client:
        entry = client.get("/")
        assert entry.status_code == 200
        assert "window.JUSTKERNEL_DEMO_ONLY=true" in entry.text
        assert entry.headers["cache-control"] == "no-store"
        assert client.get("/app.js").status_code == 200
        assert client.get("/visualization.js").status_code == 200
        assert client.get("/api/lab/health").json() == {
            "ok": True,
            "demo_only": True,
            "model_calls": False,
            "npu_configured": False,
        }
        for path in ["/api/lab/control/swarm/start", "/api/lab/workspace/judge/session/open"]:
            response = client.post(path, json={})
            assert response.status_code == 409
            assert "justkernel serve" in response.json()["detail"]
    assert not list(tmp_path.iterdir())


# ---- CLI bypasses Settings, model vaults, workspaces and official templates ---
def test_demo_cli_never_constructs_real_service_or_settings(monkeypatch):
    from aworker.lab import cli, dashboard

    def forbidden(*args, **kwargs):
        raise AssertionError("Demo must not initialize the real runtime")

    called = []
    monkeypatch.setattr(sys, "argv", ["justkernel", "demo", "--port", "4179", "--open"])
    monkeypatch.setattr(cli, "LabService", forbidden)
    monkeypatch.setattr(cli, "Settings", forbidden)
    monkeypatch.setattr(dashboard, "serve_demo", lambda *args: called.append(args))
    cli.main()
    assert called == [("127.0.0.1", 4179, True)]


# ---- real subprocess entry from an empty folder, on every CI operating system -
def test_demo_subprocess_starts_from_an_empty_directory(tmp_path):
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, "-m", "aworker.lab.cli", "demo", "--port", str(port)],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(process.stderr.read().decode(errors="replace"))
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/lab/health", timeout=1
                ) as r:
                    assert json.load(r)["demo_only"]
                break
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.1)
        else:
            raise AssertionError("Demo did not become ready")
        assert not list(tmp_path.iterdir())
    finally:
        process.terminate()
        try:
            process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=10)
