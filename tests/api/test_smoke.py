"""Routing, auth and error-shape checks that don't need a database."""

import pytest

PROTECTED = [
    ("GET", "/api/v1/auth/me"),
    ("GET", "/api/v1/dashboard"),
    ("GET", "/api/v1/today"),
    ("GET", "/api/v1/statistics"),
    ("GET", "/api/v1/wellness"),
    ("GET", "/api/v1/medications"),
    ("POST", "/api/v1/push/test"),
]


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_protected_routes_require_a_session(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 401
    assert response.json() == {"ok": False, "error": "Not signed in."}


def test_cron_requires_the_shared_secret(client):
    assert client.post("/api/v1/cron/send-reminders").status_code == 401
    bad = client.get("/api/v1/cron/send-reminders", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401


def test_validation_errors_use_the_ok_error_shape(client):
    response = client.post("/api/v1/auth/otp/request", json={"email": "nope", "purpose": "signin"})
    assert response.status_code == 422
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == "Enter a valid email address."
    assert body["details"][0]["field"] == "email"


def test_openapi_lists_every_ui_endpoint(client):
    paths = client.get("/openapi.json").json()["paths"]
    expected = {
        "/api/v1/auth/otp/request",
        "/api/v1/auth/otp/verify",
        "/api/v1/auth/signout",
        "/api/v1/auth/me",
        "/api/v1/dashboard",
        "/api/v1/today",
        "/api/v1/medications",
        "/api/v1/medications/{medication_id}",
        "/api/v1/medications/{medication_id}/enabled",
        "/api/v1/doses/completion",
        "/api/v1/statistics",
        "/api/v1/wellness",
        "/api/v1/wellness/count/increment",
        "/api/v1/wellness/count/decrement",
        "/api/v1/wellness/count/reset",
        "/api/v1/wellness/notes",
        "/api/v1/push/tokens",
        "/api/v1/push/test",
        "/api/v1/cron/send-reminders",
    }
    assert expected <= set(paths)
