from fastapi.testclient import TestClient

from app.core.build_info import APP_NAME, APP_VERSION, BUILD_LABEL, API_VERSION, runtime_identity
from app.server import create_app

def test_runtime_identity_is_single_source_of_truth(tmp_path):
    identity = runtime_identity()
    assert identity == {
        "name": APP_NAME,
        "version": APP_VERSION,
        "build": BUILD_LABEL,
        "api_version": API_VERSION,
    }

    app = create_app(
        "sqlite:///" + str(tmp_path / "build-info.sqlite"),
        origin="http://testserver",
        seed_demo=False,
    )
    client = TestClient(app)

    health = client.get("/api/health")
    live = client.get("/api/health/live")
    ready = client.get("/api/health/ready")

    assert health.status_code == 200
    assert live.status_code == 200
    assert ready.status_code == 200

    assert health.json()["build"] == BUILD_LABEL
    assert health.json()["api_version"] == API_VERSION
    assert live.json()["build"] == BUILD_LABEL
    assert ready.json()["build"] == BUILD_LABEL
    assert app.title == APP_NAME
    assert app.version == APP_VERSION
