"""PyInstaller entry point for the kernel sidecar binary.

Bundling the kernel (DESIGN.md §8) lets the desktop app run without a system
Python. Build with `python scripts/build_kernel.py` (or `pyinstaller
packaging/agent-kernel.spec`).
"""

from agent_kernel.__main__ import main

if __name__ == "__main__":
    main()
