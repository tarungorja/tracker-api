import os

# Must be set before the app (and its cached settings) are imported.
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "MONGODB_URI": "mongodb://localhost:27017/health_test",
        "AUTH_SECRET": "test-secret",
        "CRON_SECRET": "cron-test-secret",
        "ENSURE_INDEXES_ON_STARTUP": "false",
        "REMINDER_TIMER_ENABLED": "false",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402


@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        yield test_client
