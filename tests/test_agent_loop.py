"""Exercises the M1 tool-execution loop with a scripted fake provider, so the
orchestration (tool rounds, parallelism, permission gating) is verified without
a live model."""

from __future__ import annotations

from typing import Any, AsyncIterator

from agent_kernel.agent.loop import AgentLoop
from agent_kernel.events import (
    Event,
    MessageComplete,
    TextDelta,
    ToolCallResult,
    ToolCallStart,
    TurnComplete,
)
from agent_kernel.permissions import PermissionPolicy, RiskLevel
from agent_kernel.providers.base import Provider
from agent_kernel.session.store import SessionStore
from agent_kernel.tools.registry import Tool, ToolRegistry


class FakeProvider(Provider):
    """Yields a pre-scripted list of events on each successive stream() call."""

    name = "fake"

    def __init__(self, scripts: list[list[Event]]) -> None:
        self._scripts = list(scripts)
        self.seen_messages: list[list[dict[str, Any]]] = []

    async def stream(
        self, messages, *, tools=None, system=None
    ) -> AsyncIterator[Event]:
        self.seen_messages.append([dict(m) for m in messages])
        for event in self._scripts.pop(0):
            yield event


def _tool(name: str, risk: RiskLevel, result: Any) -> Tool:
    async def handler(args: dict[str, Any]) -> Any:
        return result

    return Tool(
        name=name,
        description=name,
        input_schema={"type": "object"},
        handler=handler,
        risk=risk,
    )


def _loop(tmp_path, provider, tools, policy=None) -> tuple[AgentLoop, Any]:
    store = SessionStore(tmp_path)
    session = store.create()
    loop = AgentLoop(provider, store, tools, policy=policy or PermissionPolicy("allow"))
    return loop, session


async def _drain(loop, session, text, confirm=None) -> list[Event]:
    return [e async for e in loop.run_turn(session, text, confirm)]


async def test_single_tool_round_then_answer(tmp_path):
    reg = ToolRegistry()
    reg.register(_tool("read_file", RiskLevel.READ, "file-contents"))
    provider = FakeProvider(
        [
            [
                ToolCallStart(id="c1", name="read_file", arguments={"path": "x"}),
                MessageComplete(text="", stop_reason="tool_use"),
            ],
            [
                TextDelta(text="the answer"),
                MessageComplete(text="the answer", stop_reason="end_turn"),
            ],
        ]
    )
    loop, session = _loop(tmp_path, provider, reg)

    events = await _drain(loop, session, "read x")

    results = [e for e in events if isinstance(e, ToolCallResult)]
    assert len(results) == 1
    assert results[0].result == "file-contents"
    assert not results[0].is_error

    final = events[-1]
    assert isinstance(final, TurnComplete)
    assert final.text == "the answer"

    # The tool result was fed back into the second provider call.
    assert len(provider.seen_messages) == 2
    assert any(m.get("role") == "tool" for m in provider.seen_messages[1])


async def test_parallel_tool_calls_all_execute(tmp_path):
    reg = ToolRegistry()
    reg.register(_tool("a", RiskLevel.READ, "ra"))
    reg.register(_tool("b", RiskLevel.READ, "rb"))
    provider = FakeProvider(
        [
            [
                ToolCallStart(id="c1", name="a", arguments={}),
                ToolCallStart(id="c2", name="b", arguments={}),
                MessageComplete(text="", stop_reason="tool_use"),
            ],
            [MessageComplete(text="done", stop_reason="end_turn")],
        ]
    )
    loop, session = _loop(tmp_path, provider, reg)

    events = await _drain(loop, session, "do both")
    results = {e.name: e.result for e in events if isinstance(e, ToolCallResult)}
    assert results == {"a": "ra", "b": "rb"}


async def test_denied_permission_feeds_error_back(tmp_path):
    reg = ToolRegistry()
    reg.register(_tool("write_file", RiskLevel.WRITE, "wrote"))
    provider = FakeProvider(
        [
            [
                ToolCallStart(id="c1", name="write_file", arguments={"path": "x"}),
                MessageComplete(text="", stop_reason="tool_use"),
            ],
            [MessageComplete(text="ok, skipped", stop_reason="end_turn")],
        ]
    )
    loop, session = _loop(tmp_path, provider, reg, policy=PermissionPolicy("ask"))

    async def deny(_call, _risk):
        return False

    events = await _drain(loop, session, "write x", confirm=deny)
    result = next(e for e in events if isinstance(e, ToolCallResult))
    assert result.is_error
    assert "Denied by user" in result.result


async def test_unknown_tool_is_reported(tmp_path):
    reg = ToolRegistry()
    provider = FakeProvider(
        [
            [
                ToolCallStart(id="c1", name="ghost", arguments={}),
                MessageComplete(text="", stop_reason="tool_use"),
            ],
            [MessageComplete(text="recovered", stop_reason="end_turn")],
        ]
    )
    loop, session = _loop(tmp_path, provider, reg)

    events = await _drain(loop, session, "call ghost")
    result = next(e for e in events if isinstance(e, ToolCallResult))
    assert result.is_error
    assert "Unknown tool" in result.result
