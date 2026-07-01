import pytest

from agent_kernel.tools.registry import Tool, ToolRegistry


def _echo_tool() -> Tool:
    async def handler(args):
        return args.get("value")

    return Tool(
        name="echo",
        description="Echo a value back.",
        input_schema={"type": "object", "properties": {"value": {"type": "string"}}},
        handler=handler,
    )


def test_register_and_schemas():
    reg = ToolRegistry()
    reg.register(_echo_tool())

    assert [t.name for t in reg.list()] == ["echo"]
    schema = reg.schemas()[0]
    assert schema["name"] == "echo"
    assert "input_schema" in schema


def test_duplicate_registration_rejected():
    reg = ToolRegistry()
    reg.register(_echo_tool())
    with pytest.raises(ValueError):
        reg.register(_echo_tool())


async def test_invoke_runs_handler():
    reg = ToolRegistry()
    reg.register(_echo_tool())
    result = await reg.invoke("echo", {"value": "pong"})
    assert result == "pong"


async def test_invoke_unknown_raises():
    reg = ToolRegistry()
    with pytest.raises(KeyError):
        await reg.invoke("nope", {})
