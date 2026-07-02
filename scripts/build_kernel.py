"""Build the standalone kernel sidecar binary with PyInstaller (DESIGN.md §8).

Produces `dist/agent-kernel[.exe]` — a single executable that runs the kernel
without a system Python, for use as the Tauri app's sidecar. Point the shell at
it via AGENT_KERNEL_CMD.

    python scripts/build_kernel.py
"""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "packaging", "agent-kernel.spec")


def main() -> int:
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", SPEC]
    print("running:", " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
