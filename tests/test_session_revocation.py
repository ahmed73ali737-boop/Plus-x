"""Actual app + SQLite session management behavior tests.

These tests must run with the canonical PulseX consolidated source.  They do
not assert availability of an external IAM provider or a user/device mapping.
"""
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.db import users
from app.server import create_app


def boot(tmp_path):
    app = create_app(
        "sqlite:///" + str(tmp_path / "px-session-revocation.sqlite"),
        origin="http://testserver",
        seed_demo=True,
    )
    assert len(app.state.seed_credentials) >= 3
    return app


def login(client, credentials):
    response = client.post("/api/auth/login", json={
        "email": credentials["email"],
        "password": credentials["password"],
    })
    assert response.status_code == 200
    return response.json()["csrf"]


def test_session_summary_is_owner_scoped_and_revoke_all_is_csrf_protected(tmp_path):
    app = boot(tmp_path)
    primary = app.state.seed_credentials[0]
    another = app.state.seed_credentials[2]
    with TestClient(app) as first, TestClient(app) as second, TestClient(app) as outsider:
        csrf = login(first, primary)
        _ = login(second, primary)
        _ = login(outsider, another)

        summary = first.get("/api/auth/sessions")
        assert summary.status_code == 200
        assert summary.json()["active_count"] == 2
        assert summary.json()["absolute_timeout_seconds"] == 28800
        assert summary.json()["device_inventory_available"] is False
        assert summary.json()["current_expires_at"]
        assert "token_hash" not in summary.text
        assert "csrf" not in summary.text

        assert first.post("/api/auth/sessions/revoke-all").status_code == 403
        assert first.post(
            "/api/auth/sessions/revoke-all", headers={"X-CSRF": "wrong"}
        ).status_code == 403
        assert second.get("/api/auth/me").status_code == 200

        revoked = first.post(
            "/api/auth/sessions/revoke-all", headers={"X-CSRF": csrf}
        )
        assert revoked.status_code == 200
        assert revoked.json() == {"ok": True, "revoked_sessions": 2}
        assert first.get("/api/auth/me").status_code == 401
        assert second.get("/api/auth/me").status_code == 401

        # Another user's session must remain valid after owner-wide revoke.
        assert outsider.get("/api/auth/me").status_code == 200
        assert outsider.get("/api/auth/sessions").json()["active_count"] == 1


def test_forced_password_change_user_can_still_revoke_suspicious_sessions(tmp_path):
    app = boot(tmp_path)
    primary = app.state.seed_credentials[0]
    with TestClient(app) as client:
        csrf = login(client, primary)
        me = client.get("/api/auth/me").json()
        with app.state.engine.begin() as connection:
            connection.execute(
                update(users)
                .where(users.c.id == me["user"]["id"])
                .values(must_change_password=1)
            )

        assert client.get("/api/auth/sessions").status_code == 200
        assert client.post(
            "/api/auth/sessions/revoke-all", headers={"X-CSRF": csrf}
        ).status_code == 200
        assert client.get("/api/auth/me").status_code == 401


def test_anonymous_request_cannot_learn_session_counts_or_revoke(tmp_path):
    app = boot(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/auth/sessions").status_code == 401
        assert client.post(
            "/api/auth/sessions/revoke-all", headers={"X-CSRF": "random"}
        ).status_code == 401
