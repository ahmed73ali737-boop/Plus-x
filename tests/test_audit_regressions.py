from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import event_guests, guests
from app.server import create_app
from tools.migrate_postgres import MIGRATIONS


def boot(tmp_path):
    app = create_app(
        "sqlite:///" + str(tmp_path / "audit-regressions.sqlite"),
        origin="http://testserver",
        seed_demo=True,
    )
    return app, TestClient(app)


def guest_counts(app):
    with app.state.engine.connect() as conn:
        return (
            conn.execute(select(func.count()).select_from(guests)).scalar_one(),
            conn.execute(select(func.count()).select_from(event_guests)).scalar_one(),
        )


def invalid_guest(client, phone, client_id=None):
    item = {
        "phone": phone,
        "country_code": "+967",
        "consent": True,
        "pass_token": "short-token",
    }
    if client_id is not None:
        item["client_id"] = client_id
    return item


def test_direct_invalid_guest_registration_is_atomic(tmp_path):
    app, client = boot(tmp_path)
    before = guest_counts(app)
    response = client.post(
        "/api/public/events/demo/guests/register",
        json=invalid_guest(client, "777010101"),
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "PASS_TOKEN_INVALID"
    assert guest_counts(app) == before


def test_rejected_offline_guest_sync_is_atomic(tmp_path):
    app, client = boot(tmp_path)
    before = guest_counts(app)
    response = client.post(
        "/api/public/events/demo/guests/sync",
        json={"items": [invalid_guest(client, "777010102", "rejected-1")]},
    )
    assert response.status_code == 200
    receipt = response.json()["receipts"][0]
    assert receipt["client_id"] == "rejected-1"
    assert receipt["status"] == "rejected"
    assert receipt["error"] == "PASS_TOKEN_INVALID"
    assert guest_counts(app) == before


def test_mixed_guest_sync_commits_only_accepted_item(tmp_path):
    app, client = boot(tmp_path)
    before_guests, before_regs = guest_counts(app)
    accepted = {
        "client_id": "accepted-1",
        "phone": "777010103",
        "country_code": "+967",
        "consent": True,
        "name": "Accepted",
    }
    rejected = invalid_guest(client, "777010104", "rejected-1")
    response = client.post(
        "/api/public/events/demo/guests/sync",
        json={"items": [accepted, rejected]},
    )
    assert response.status_code == 200
    receipts = response.json()["receipts"]
    assert [x["status"] for x in receipts] == ["accepted", "rejected"]
    assert receipts[1]["error"] == "PASS_TOKEN_INVALID"
    assert guest_counts(app) == (before_guests + 1, before_regs + 1)


def test_malformed_host_is_rejected_and_api_headers_are_preserved(tmp_path):
    _, client = boot(tmp_path)
    response = client.post(
        "/api/auth/login",
        headers={"Host": "testserver/other"},
        json={"email": "none@example.com", "password": "not-the-right-password"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "HOST_INVALID"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-pulsex-api-version"] == "1"


def test_normal_host_login_rate_limit_still_applies(tmp_path):
    _, client = boot(tmp_path)
    statuses = [
        client.post(
            "/api/auth/login",
            json={"email": "none@example.com", "password": "not-the-right-password"},
        ).status_code
        for _ in range(21)
    ]
    assert statuses[:20] == [401] * 20
    assert statuses[20] == 429


def test_postgres_migration_chain_includes_event_guest_pass_number():
    assert MIGRATIONS[-1].name == "007_event_guest_pass_number.sql"
