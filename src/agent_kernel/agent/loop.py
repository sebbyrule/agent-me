"""The agent loop — provider-agnostic orchestration (DESIGN.md §4.1).

M1 shape: receive user input, then repeat {call provider -> if it requests
tools, gate them through the permission policy, execute the approved ones (in
parallel), feed results back} until the provider returns a final text answer with
no tool requests. Emits the kernel's normalized event stream throughout, so the
CLI and desktop render the same thing.

Provider-neutral message history (what lives in `session.messages`):

    {"role": "user", "content": str}
    {"role": "assistant", "content": str}
    {"role": "assistant", "content": str,
        "tool_calls": [{"id", "name", "arguments": {...}}]}
    {"role": "tool",
        "tool_results": [{"id", "name", "result", "is_error"}]}

Each provider adapter translates this neutral shape into its own wire format, so
the loop never branches on provider (principle #1, DESIGN.md §5).
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Awaitable, Callable

from ..events import (
    Event,
    MessageComplete,
    ToolCallResult,
    ToolCallStart,
    TurnComplete,
)
from ..permissions import Decision, PermissionPolicy, RiskLevel
from ..providers.base import Provider
from ..session.store import Session, SessionStore
from ..tools.registry import ToolRegistry

# Called to confirm a risky tool call. Returns True to approve. The frontend
# owns the UX; the kernel owns the policy (DESIGN.md §8).
ConfirmCallback = Callable[[ToolCallStart, RiskLevel], Awaitable[bool]]

# Safety valve so a misbehaving model can't spin tool rounds forever.
MAX_TOOL_ROUNDS = 12


async def _always_allow(_call: ToolCallStart, _risk: RiskLevel) -> bool:
    return True


class AgentLoop:
    def __init__(
        self,
        provider: Provider,
        store: SessionStore,
        tools: ToolRegistry,
        *,
        policy: PermissionPolicy | None = None,
        system: str | None = None,
    ) -> None:
        self._provider = provider
        self._store = store
        self._tools = tools
        self._policy = policy or PermissionPolicy()
        self._system = system

    async def run_turn(
        self,
        session: Session,
        user_input: str,
        confirm: ConfirmCallback | None = None,
    ) -> AsyncIterator[Event]:
        confirm = confirm or _always_allow
        session.add_message("user", user_input)

        tool_schemas = self._tools.schemas() or None
        final_text = ""

        for _round in range(MAX_TOOL_ROUNDS):
            tool_calls: list[ToolCallStart] = []
            final_text = ""
            async for event in self._provider.stream(
                session.messages, tools=tool_schemas, system=self._system
            ):
                if isinstance(event, ToolCallStart):
                    tool_calls.append(event)
                elif isinstance(event, MessageComplete):
                    final_text = event.text
                yield event

            if not tool_calls:
                # A plain text answer — the turn is done.
                if final_text:
                    session.add_message("assistant", final_text)
                self._store.save(session)
                yield TurnComplete(text=final_text)
                return

            # Record the assistant's tool request, execute, and feed results back.
            session.append(
                {
                    "role": "assistant",
                    "content": final_text,
                    "tool_calls": [
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in tool_calls
                    ],
                }
            )
            results = await self._execute_tools(tool_calls, confirm)
            for result in results:
                yield result
            session.append(
                {
                    "role": "tool",
                    "tool_results": [
                        {
                            "id": r.id,
                            "name": r.name,
                            "result": r.result,
                            "is_error": r.is_error,
                        }
                        for r in results
                    ],
                }
            )
            self._store.save(session)

        # Exhausted the round budget without a final answer.
        yield TurnComplete(text=final_text)

    async def _execute_tools(
        self, tool_calls: list[ToolCallStart], confirm: ConfirmCallback
    ) -> list[ToolCallResult]:
        """Gate each call through the permission policy, then run the approved
        ones in parallel. Results are returned in the original call order.
        """
        results: dict[str, ToolCallResult] = {}
        approved: list[tuple[ToolCallStart, Any]] = []

        # Permission decisions are resolved sequentially — an ASK may prompt the
        # user, which can't be parallelized cleanly.
        for tc in tool_calls:
            tool = self._tools.get(tc.name)
            if tool is None:
                results[tc.id] = ToolCallResult(
                    id=tc.id, name=tc.name, result=f"Unknown tool: {tc.name}", is_error=True
                )
                continue
            decision = self._policy.decide(tool.risk)
            if decision == Decision.DENY:
                results[tc.id] = ToolCallResult(
                    id=tc.id, name=tc.name, result="Denied by policy.", is_error=True
                )
                continue
            if decision == Decision.ASK and not await confirm(tc, tool.risk):
                results[tc.id] = ToolCallResult(
                    id=tc.id, name=tc.name, result="Denied by user.", is_error=True
                )
                continue
            approved.append((tc, tool))

        async def run_one(tc: ToolCallStart, tool: Any) -> ToolCallResult:
            try:
                result = await tool.handler(tc.arguments)
                return ToolCallResult(id=tc.id, name=tc.name, result=result)
            except Exception as exc:  # tool failures feed back to the model
                return ToolCallResult(
                    id=tc.id,
                    name=tc.name,
                    result=f"{type(exc).__name__}: {exc}",
                    is_error=True,
                )

        if approved:
            done = await asyncio.gather(*(run_one(tc, tool) for tc, tool in approved))
            for result in done:
                results[result.id] = result

        return [results[tc.id] for tc in tool_calls]
