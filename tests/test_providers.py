"""Runtime provider/model switching endpoints (M-post: UI provider switch)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from agent_kernel.api.app import create_app


def _client(monkeypatch) -> TestClient:
    monkeypatch.setenv("AGENT_PROVIDER", "anthropic")  # deterministic default
    return TestClient(create_app())


def test_providers_lists_all_and_current(monkeypatch):
    body = _client(monkeypatch).get("/providers").json()
    assert set(body["providers"]) == {"anthropic", "openai", "lmstudio", "ollama"}
    assert body["current"] == "anthropic"
    assert body["model"]  # anthropic default model


def test_switch_provider_resets_to_that_default_model(monkeypatch):
    client = _client(monkeypatch)
    body = client.post("/provider", json={"provider": "ollama"}).json()
    assert body["current"] == "ollama"
    assert body["model"] == "llama3.2"  # ollama default
    # /health reflects the active provider now.
    assert client.get("/health").json()["provider"] == "ollama"


def test_switch_provider_with_explicit_model(monkeypatch):
    client = _client(monkeypatch)
    body = client.post("/provider", json={"provider": "openai", "model": "gpt-4o"}).json()
    assert body["current"] == "openai"
    assert body["model"] == "gpt-4o"


def test_set_model_only(monkeypatch):
    client = _client(monkeypatch)
    body = client.post("/provider", json={"model": "claude-sonnet-5"}).json()
    assert body["current"] == "anthropic"
    assert body["model"] == "claude-sonnet-5"


def test_unknown_provider_rejected(monkeypatch):
    resp = _client(monkeypatch).post("/provider", json={"provider": "bogus"})
    assert resp.status_code == 400
