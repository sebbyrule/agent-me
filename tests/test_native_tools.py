import pytest

from agent_kernel.permissions import RiskLevel
from agent_kernel.tools import register_native_tools
from agent_kernel.tools.native import WorkspaceError
from agent_kernel.tools.registry import ToolRegistry


def _registry(workspace) -> ToolRegistry:
    reg = ToolRegistry()
    register_native_tools(reg, workspace)
    return reg


def test_native_tools_registered_with_expected_risk(tmp_path):
    by_name = {t.name: t for t in _registry(tmp_path).list()}
    assert by_name["read_file"].risk == RiskLevel.READ
    assert by_name["list_dir"].risk == RiskLevel.READ
    assert by_name["write_file"].risk == RiskLevel.WRITE
    assert by_name["run_shell"].risk == RiskLevel.EXEC


async def test_write_then_read_roundtrip(tmp_path):
    reg = _registry(tmp_path)
    msg = await reg.invoke("write_file", {"path": "nested/note.txt", "content": "hello"})
    assert "Wrote" in msg
    assert (tmp_path / "nested" / "note.txt").read_text(encoding="utf-8") == "hello"
    assert await reg.invoke("read_file", {"path": "nested/note.txt"}) == "hello"


async def test_list_dir(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    entries = await _registry(tmp_path).invoke("list_dir", {"path": "."})
    assert "a.txt" in entries and "sub/" in entries


async def test_run_shell_returns_output_and_runs_in_workspace(tmp_path):
    reg = _registry(tmp_path)
    result = await reg.invoke("run_shell", {"command": "echo hello-shell"})
    assert result["exit_code"] == 0
    assert "hello-shell" in result["stdout"]


async def test_read_rejects_path_traversal(tmp_path):
    reg = _registry(tmp_path)
    with pytest.raises(WorkspaceError):
        await reg.invoke("read_file", {"path": "../outside.txt"})


async def test_write_rejects_absolute_escape(tmp_path):
    reg = _registry(tmp_path)
    with pytest.raises(WorkspaceError):
        await reg.invoke("write_file", {"path": "C:/Windows/evil.txt", "content": "x"})
