"""Deployment configuration smoke tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_render_blueprint_exists():
    assert (ROOT / "render.yaml").is_file()


def test_production_start_script_exists_and_uses_port():
    script = ROOT / "scripts" / "start.sh"
    assert script.is_file()
    content = script.read_text(encoding="utf-8")
    assert "0.0.0.0" in content
    assert "PORT" in content
    assert "python -m uvicorn app.main:app" in content


def test_env_not_tracked_by_gitignore():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore


def test_production_start_command_boots_and_serves_privacy():
    env = os.environ.copy()
    env["PORT"] = "8766"
    env["HOST"] = "127.0.0.1"
    venv_bin = ROOT / ".venv" / "bin"
    if venv_bin.is_dir():
        env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"
    proc = subprocess.Popen(
        ["bash", str(ROOT / "scripts" / "start.sh")],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        import time

        import httpx

        deadline = time.time() + 10
        last_error = None
        while time.time() < deadline:
            try:
                with httpx.Client(base_url="http://127.0.0.1:8766", timeout=1.0) as client:
                    home = client.get("/")
                    shop = client.get("/shop")
                    privacy = client.get("/privacy")
                assert home.status_code == 200
                assert shop.status_code == 200
                assert privacy.status_code == 200
                assert "Privacy Policy" in privacy.text
                assert "druvo.uk@gmail.com" in privacy.text
                return
            except Exception as exc:  # noqa: BLE001 - retry until timeout
                last_error = exc
                time.sleep(0.25)
        raise AssertionError(f"Production server did not become ready: {last_error}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
