"""A deployment missing required env vars should explain itself instead of crashing."""

import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_missing_settings_produce_a_readable_503_instead_of_a_crash(tmp_path):
    script = textwrap.dedent(
        """
        from fastapi.testclient import TestClient
        from app.main import app  # must import without raising

        client = TestClient(app)
        for path in ("/docs", "/health", "/api/v1/today"):
            r = client.get(path)
            assert r.status_code == 503, (path, r.status_code)
            body = r.json()
            assert body["ok"] is False
            assert "MONGODB_URI" in body["error"] and "AUTH_SECRET" in body["error"], body
        print("OK")
        """
    )
    # Run from an empty directory with no .env and no settings in the environment.
    import os

    env = {
        k: v for k, v in os.environ.items() if k not in {"MONGODB_URI", "AUTH_SECRET", "ENV_FILE"}
    }
    env["PYTHONPATH"] = str(ROOT)
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout
