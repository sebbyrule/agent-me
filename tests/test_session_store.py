from agent_kernel.session.store import SessionStore


def test_create_and_roundtrip(tmp_path):
    store = SessionStore(tmp_path)
    session = store.create()

    assert store.exists(session.id)

    session.add_message("user", "hello")
    session.add_message("assistant", "hi there")
    store.save(session)

    loaded = store.get(session.id)
    assert loaded is not None
    assert loaded.id == session.id
    assert loaded.messages == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]


def test_get_missing_returns_none(tmp_path):
    store = SessionStore(tmp_path)
    assert store.get("does-not-exist") is None
