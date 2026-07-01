# desktop/ — Tauri app (deferred to M4)

Placeholder. Per DESIGN.md §7, the Tauri desktop app is **M4** and must not be
started until the CLI has proven the kernel end-to-end (M0–M3).

When M4 begins, this directory will hold:

- **Rust shell** (`src-tauri/`) — spawns the Python kernel as a **sidecar** on
  launch, health-checks it, and shuts it down gracefully on exit.
- **WebView frontend** — a chat-first UI that talks to the kernel over the *same*
  local API the CLI uses (DESIGN.md §4.3). No second implementation of the agent
  loop; no reaching into kernel internals.
- Later (M5): a toggleable read-only project/file viewer pane.

Sidecar packaging (PyInstaller vs. system Python) is an open question to decide
near M4, not now (DESIGN.md §8).
