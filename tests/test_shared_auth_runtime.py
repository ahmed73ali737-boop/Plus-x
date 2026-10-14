"""Guard the optional shared IAM runtime switch without faking a real IAM provider."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.server import create_app


class DenyPort:
    def __init__(self):
        self.questions = []

    def allow(self, question):
        self.questions.append(question)
        return False


def test_enforcement_requires_provider_before_db_creation(monkeypatch, tmp_path):
    monkeypatch.setenv("PULSEX_SHARED_AUTHORIZATION_MODE", "Enforce")
    def must_not_open_db(*args, **kwargs):
        pytest.fail("DB must not be opened without required shared provider")
    monkeypatch.setattr("app.server.make_engine", must_not_open_db)
    with pytest.raises(RuntimeError, match="SHARED_AUTHORIZATION_PROVIDER_REQUIRED"):
        create_app("sqlite:///" + str(tmp_path / "iam.sqlite3"), seed_demo=False)


def test_invalid_mode_is_not_permissive(monkeypatch):
    monkeypatch.setenv("PULSEX_SHARED_AUTHORIZATION_MODE", "AllowAll")
    with pytest.raises(RuntimeError, match="SHARED_AUTHORIZATION_MODE_INVALID"):
        create_app(seed_demo=False)


def test_shared_denial_blocks_draft_and_publish_after_local_scope(monkeypatch, tmp_path):
    monkeypatch.setenv("PULSEX_SHARED_AUTHORIZATION_MODE", "Enforce")
    port = DenyPort()
    app = create_app("sqlite:///" + str(tmp_path / "iam2.sqlite3"),
                     origin="http://testserver", seed_demo=True,
                     shared_authorizer=port)
    client = TestClient(app)
    identity = app.state.seed_credentials[2]
    login = client.post("/api/auth/login", json={
        "email": identity["email"], "password": identity["password"]})
    assert login.status_code == 200
    client.headers["X-CSRF"] = login.json()["csrf"]
    site = client.get("/api/admin/sites/agency-01").json()
    response = client.put("/api/admin/sites/agency-01", json={
        "draft_rev": site["draft_rev"], "config": site["draft"]})
    assert response.status_code == 403
    assert response.json()["detail"] == "SHARED_AUTHORIZATION_FORBIDDEN"
    response = client.post("/api/admin/sites/agency-01/publish", json={
        "draft_rev": site["draft_rev"]})
    assert response.status_code == 403
    assert response.json()["detail"] == "SHARED_AUTHORIZATION_FORBIDDEN"
    assert [q.action for q in port.questions] == ["event.configure", "event.publish"]
    assert all(q.site_id == "agency-01" for q in port.questions)
