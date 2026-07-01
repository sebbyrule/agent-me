"""The kernel serves the desktop chat UI and allows cross-origin calls (M4), so
both the browser-served UI and Tauri's bundled webview reach one kernel."""

from fastapi.testclient import TestClient

from agent_kernel.api.app import create_app


def test_health_reports_provider():
    client = TestClient(create_app())
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert "provider" in body


def test_root_redirects_to_app():
    client = TestClient(create_app())
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/app/"


def test_app_serves_ui():
    client = TestClient(create_app())
    resp = client.get("/app/")
    assert resp.status_code == 200
    assert "<title>agent-me</title>" in resp.text


def test_cors_allows_cross_origin():
    client = TestClient(create_app())
    resp = client.get("/health", headers={"Origin": "http://tauri.localhost"})
    assert resp.headers.get("access-control-allow-origin") == "*"
