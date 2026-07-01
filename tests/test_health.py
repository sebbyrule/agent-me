from fastapi.testclient import TestClient

from agent_kernel.api.app import create_app


def test_health_ok_without_api_key():
    # /health must work even before a provider key is configured.
    app = create_app()
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_mcp_connect_not_implemented():
    client = TestClient(create_app())
    resp = client.post("/mcp/connect")
    assert resp.status_code == 501
