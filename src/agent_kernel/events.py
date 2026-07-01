"""The kernel's internal, provider-agnostic event stream.

Every provider adapter normalizes its native streaming format into these events
(DESIGN.md §5) so the agent loop and the API layer never branch on provider.
The same events are serialized over the WebSocket to frontends.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class TextDelta:
    """An incremental chunk of assistant text."""

    text: str
    type: Literal["text_delta"] = "text_delta"


@dataclass
class ToolCallStart:
    """The model has begun requesting a tool call. (Wired up in M1.)"""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    type: Literal["tool_call_start"] = "tool_call_start"


@dataclass
class ToolCallResult:
    """The result of executing a tool call, fed back to the model. (M1.)"""

    id: str
    name: str
    result: Any = None
    is_error: bool = False
    type: Literal["tool_call_result"] = "tool_call_result"


@dataclass
class MessageComplete:
    """A full assistant turn finished."""

    text: str
    stop_reason: str | None = None
    type: Literal["message_complete"] = "message_complete"


@dataclass
class ErrorEvent:
    """A recoverable error surfaced to the client instead of dropping the stream."""

    message: str
    type: Literal["error"] = "error"


Event = TextDelta | ToolCallStart | ToolCallResult | MessageComplete | ErrorEvent


def to_wire(event: Event) -> dict[str, Any]:
    """Serialize an event to a JSON-safe dict for the WebSocket."""
    return event.__dict__.copy()
