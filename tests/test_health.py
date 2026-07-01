from fastapi.testclient import TestClient

from agent_kernel.api.app import create_app


def test_health_ok_without_api_key():
    # /health must work even before a provider key is configured.
    app = create_app()
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_mcp_connect_requires_a_body():
    # The endpoint is implemented (M2); calling it without a server spec is a
    # validation error, not a 501. The happy path (spawning a real server) is
    # covered by the MCP integration tests and the live smoke.
    client = TestClient(create_app())
    resp = client.post("/mcp/connect")
    assert resp.status_code == 422
