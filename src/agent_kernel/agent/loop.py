"""The agent loop — provider-agnostic orchestration (DESIGN.md §4.1).

M0 shape: receive user input -> call the provider -> stream the assistant reply
-> persist the turn. Tool calls (including parallel tool calls) are handled here
in M1; the loop is structured so that adding them does not change the provider
interface or the frontends.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from ..events import Event, MessageComplete
from ..providers.base import Provider
from ..session.store import Session, SessionStore
from ..tools.registry import ToolRegistry


class AgentLoop:
    def __init__(
        self,
        provider: Provider,
        store: SessionStore,
        tools: ToolRegistry,
        *,
        system: str | None = None,
    ) -> None:
        self._provider = provider
        self._store = store
        self._tools = tools
        self._system = system

    async def run_turn(
        self, session: Session, user_input: str
    ) -> AsyncIterator[Event]:
        """Run one user turn, yielding normalized events as they stream.

        In M1 this becomes a loop: while the provider asks for tools, execute
        them (in parallel), append results, and call the provider again until a
        final text answer. For M0 it is a single provider call.
        """
        session.add_message("user", user_input)

        tool_schemas = self._tools.schemas() or None
        final_text = ""
        async for event in self._provider.stream(
            session.messages, tools=tool_schemas, system=self._system
        ):
            if isinstance(event, MessageComplete):
                final_text = event.text
            yield event

        if final_text:
            session.add_message("assistant", final_text)
        self._store.save(session)
