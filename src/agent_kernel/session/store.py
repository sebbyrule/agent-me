"""File-based session persistence.

Each session is one JSON file: `<session_dir>/<id>.session.json`, holding the
provider-neutral message history so a conversation survives kernel restarts
(DESIGN.md §4.1). Concurrency is single-process/simple for now; revisit with
SQLite when multiple concurrent sessions appear (DESIGN.md §8).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Session:
    id: str
    messages: list[dict[str, Any]] = field(default_factory=list)

    def add_message(self, role: str, content: Any) -> None:
        self.messages.append({"role": role, "content": content})

    def append(self, message: dict[str, Any]) -> None:
        """Append a full, provider-neutral message dict (e.g. an assistant turn
        carrying `tool_calls`, or a `tool` message carrying `tool_results`).
        """
        self.messages.append(message)


class SessionStore:
    def __init__(self, session_dir: Path) -> None:
        self._dir = Path(session_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.session.json"

    def create(self) -> Session:
        session = Session(id=uuid.uuid4().hex)
        self.save(session)
        return session

    def get(self, session_id: str) -> Session | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return Session(id=data["id"], messages=data.get("messages", []))

    def save(self, session: Session) -> None:
        payload = {"id": session.id, "messages": session.messages}
        self._path(session.id).write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

    def exists(self, session_id: str) -> bool:
        return self._path(session_id).exists()

    def list_sessions(self) -> list[dict[str, Any]]:
        """Summaries of all persisted sessions (survives kernel restarts)."""
        out: list[dict[str, Any]] = []
        for path in sorted(self._dir.glob("*.session.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            out.append(
                {"id": data.get("id"), "messages": len(data.get("messages", []))}
            )
        return out
