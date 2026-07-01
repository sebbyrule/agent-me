from agent_kernel.events import (
    ErrorEvent,
    MessageComplete,
    TextDelta,
    ToolCallStart,
    to_wire,
)


def test_text_delta_wire_shape():
    wire = to_wire(TextDelta(text="hi"))
    assert wire == {"text": "hi", "type": "text_delta"}


def test_message_complete_wire_shape():
    wire = to_wire(MessageComplete(text="done", stop_reason="end_turn"))
    assert wire["type"] == "message_complete"
    assert wire["text"] == "done"
    assert wire["stop_reason"] == "end_turn"


def test_error_event_wire_shape():
    wire = to_wire(ErrorEvent(message="boom"))
    assert wire == {"message": "boom", "type": "error"}


def test_tool_call_start_defaults():
    wire = to_wire(ToolCallStart(id="t1", name="read_file"))
    assert wire["type"] == "tool_call_start"
    assert wire["arguments"] == {}
