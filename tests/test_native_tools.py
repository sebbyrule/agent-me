from agent_kernel.permissions import RiskLevel
from agent_kernel.tools import register_native_tools
from agent_kernel.tools.registry import ToolRegistry


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    register_native_tools(reg)
    return reg


def test_native_tools_registered_with_expected_risk():
    reg = _registry()
    by_name = {t.name: t for t in reg.list()}
    assert by_name["read_file"].risk == RiskLevel.READ
    assert by_name["list_dir"].risk == RiskLevel.READ
    assert by_name["write_file"].risk == RiskLevel.WRITE
    assert by_name["run_shell"].risk == RiskLevel.EXEC


async def test_write_then_read_roundtrip(tmp_path):
    reg = _registry()
    target = tmp_path / "nested" / "note.txt"

    msg = await reg.invoke("write_file", {"path": str(target), "content": "hello"})
    assert "Wrote" in msg
    assert target.read_text(encoding="utf-8") == "hello"

    content = await reg.invoke("read_file", {"path": str(target)})
    assert content == "hello"


async def test_list_dir(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    reg = _registry()
    entries = await reg.invoke("list_dir", {"path": str(tmp_path)})
    assert "a.txt" in entries
    assert "sub/" in entries


async def test_run_shell_returns_exit_and_output():
    reg = _registry()
    result = await reg.invoke("run_shell", {"command": "echo hello-shell"})
    assert result["exit_code"] == 0
    assert "hello-shell" in result["stdout"]
