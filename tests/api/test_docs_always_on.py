import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.mark.parametrize("environment", ["development", "test", "production"])
def test_docs_are_available_in_every_environment(environment):
    settings = Settings(
        _env_file=None,
        mongodb_uri="mongodb://x/y",
        auth_secret="s",
        environment=environment,
        reminder_timer_enabled=False,
        ensure_indexes_on_startup=False,
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/docs").status_code == 200
        schema = client.get("/openapi.json")
        assert schema.status_code == 200
        assert "/api/v1/today" in schema.json()["paths"]
        # Public docs, but the data endpoints still need a session.
        assert client.get("/api/v1/dashboard").status_code == 401
