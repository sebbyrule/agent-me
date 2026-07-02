"""M5 kernel surface: read-only file viewer API (sandboxed) and session
persistence endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from agent_kernel.api.app import create_app


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("SESSION_DIR", str(tmp_path / "sessions"))
    (tmp_path / "hello.txt").write_text("hi from workspace", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "nested.txt").write_text("deep", encoding="utf-8")
    return TestClient(create_app())


def test_files_tree_lists_workspace(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    body = client.get("/files/tree").json()
    names = {e["name"]: e["type"] for e in body["entries"]}
    assert names["hello.txt"] == "file"
    assert names["sub"] == "dir"


def test_files_list_is_flat_and_skips_heavy_dirs(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("x", encoding="utf-8")
    client = _client(tmp_path, monkeypatch)
    files = client.get("/files/list").json()["files"]
    assert "hello.txt" in files
    assert "sub/nested.txt" in files  # recursive, posix-style
    assert not any(f.startswith(".git/") for f in files)  # heavy dirs skipped


def test_files_read_returns_content(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    body = client.get("/files/read", params={"path": "hello.txt"}).json()
    assert body["content"] == "hi from workspace"
    assert body["truncated"] is False


def test_files_read_rejects_path_traversal(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/files/read", params={"path": "../../etc/passwd"})
    assert resp.status_code == 404


def test_sessions_persist_and_list(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    session_id = client.post("/session").json()["id"]

    listed = client.get("/sessions").json()["sessions"]
    assert any(s["id"] == session_id for s in listed)

    # A fresh app over the same SESSION_DIR still finds it (survives restart).
    reborn = TestClient(create_app())
    fetched = reborn.get(f"/session/{session_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == session_id


def test_get_unknown_session_404(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.get("/session/nope").status_code == 404
