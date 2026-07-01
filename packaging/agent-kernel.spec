# PyInstaller spec for the agent-me kernel sidecar (one-file executable).
# Build: pyinstaller packaging/agent-kernel.spec   (from the repo root)
import os

# SPECPATH is the directory containing this spec (i.e. packaging/).
ROOT = os.path.dirname(SPECPATH)
FRONTEND = os.path.join(ROOT, "desktop", "frontend")

# uvicorn resolves its loop/protocol implementations by dynamic import, so they
# must be named explicitly for PyInstaller to include them.
hiddenimports = [
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "uvicorn.logging",
]

a = Analysis(
    [os.path.join(SPECPATH, "kernel_entry.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[],
    datas=[(FRONTEND, "frontend")],  # so the frozen kernel can serve /app too
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PIL", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="agent-kernel",
    console=True,
    disable_windowed_traceback=False,
    upx=False,
)
