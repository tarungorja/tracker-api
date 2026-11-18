import base64
import json

import pytest

from app.integrations.fcm import FcmConfigError, parse_service_account

ACCOUNT = {
    "project_id": "p",
    "client_email": "svc@p.iam.gserviceaccount.com",
    "private_key": "-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----\\n",
}


def test_parses_raw_quoted_and_base64_json():
    raw = json.dumps(ACCOUNT)
    assert parse_service_account(raw)["project_id"] == "p"
    assert parse_service_account(f"'{raw}'")["project_id"] == "p"
    assert parse_service_account(json.dumps(raw))["project_id"] == "p"
    assert parse_service_account(base64.b64encode(raw.encode()).decode())["project_id"] == "p"


def test_tolerates_real_newlines_inside_private_key():
    raw = json.dumps(ACCOUNT).replace("\\\\n", "\n")
    assert parse_service_account(raw)["client_email"] == ACCOUNT["client_email"]


def test_rejects_garbage():
    with pytest.raises(FcmConfigError):
        parse_service_account("not json")
