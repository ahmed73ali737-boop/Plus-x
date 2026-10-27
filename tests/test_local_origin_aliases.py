from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.middleware import install_security_middleware


def _app(*, local_aliases: bool) -> FastAPI:
    app = FastAPI()
    install_security_middleware(
        app,
        "http://localhost:2283",
        allow_local_loopback_origins=local_aliases,
    )

    @app.post("/write")
    def write():
        return {"ok": True}

    return app


def test_local_loopback_origins_accept_both_compose_entry_points():
    client = TestClient(_app(local_aliases=True))

    for origin in (
        "http://localhost:2283",
        "http://127.0.0.1:2283",
        "http://localhost:2282",
        "http://127.0.0.1:2282",
    ):
        response = client.post("/write", headers={"Origin": origin})
        assert response.status_code == 200, origin


def test_local_origin_aliases_do_not_allow_foreign_or_production_origins():
    local_client = TestClient(_app(local_aliases=True))
    assert local_client.post("/write", headers={"Origin": "https://evil.example"}).status_code == 403

    production_client = TestClient(_app(local_aliases=False))
    assert production_client.post("/write", headers={"Origin": "http://127.0.0.1:2283"}).status_code == 403
