# desktop/ — Tauri desktop shell (M4)

A chat-first desktop app that is a **thin frontend over the kernel** (DESIGN.md §4.3).
Per "one kernel, two frontends," the Rust side owns only the kernel sidecar's lifecycle;
all agent logic stays in the kernel, reached over the same HTTP/WS API the CLI uses.

```
desktop/
  frontend/         # the chat UI (vanilla HTML/CSS/JS, no build step)
    index.html
    style.css
    app.js
  src-tauri/        # the Rust shell
    src/main.rs     # spawn kernel sidecar -> health-check -> show window -> kill on exit
    tauri.conf.json
    Cargo.toml
    build.rs
    icons/          # placeholder icons (regenerate with `tauri icon` before shipping)
  package.json      # `npm run tauri dev` / `build`
```

## The UI

`frontend/` is plain HTML/JS with no bundler, so it runs anywhere the kernel is reachable
and is what Tauri bundles into the WebView. It resolves the kernel base URL from
`window.location`, falling back to `http://127.0.0.1:8765` (the Tauri `tauri://` origin),
which is why the kernel enables permissive CORS for localhost.

It renders the full session experience: streamed tokens, tool-call chips, tool results,
and an Allow/Deny prompt when the kernel's permission policy asks to confirm a risky tool.

**Run it in a browser (no Tauri needed):** start the kernel, then open its served copy —
```bash
agent-kernel                     # serves the UI at /app
# browse to http://127.0.0.1:8765/app/
```
This is the exact UI the desktop window shows, and how M4 was verified end-to-end.

## The desktop window (Tauri)

```bash
cd desktop
npm install            # fetches @tauri-apps/cli
npm run tauri dev      # spawns the kernel, waits for /health, shows the window
```

The shell runs `python -m agent_kernel` as the sidecar and terminates it when the window
closes. Point it at a specific interpreter with `AGENT_KERNEL_CMD` (e.g. a venv python).

### Requirements to build/run the window here
- Rust toolchain (Cargo) and Node/npm — both present in this repo's environment.
- **WebView2** runtime on Windows (bundled with modern Windows; installer available from
  Microsoft otherwise).
- App icons: the committed `icons/*.png` are flat-color placeholders so the project
  compiles; run `npm run tauri icon path/to/logo.png` to generate a real set (incl. the
  `.ico`/`.icns` needed for installers) before distributing.

## Sidecar packaging decision (DESIGN.md §8)

For M4 the shell uses **system Python** and runs `python -m agent_kernel`. Bundling the
interpreter (PyInstaller vs. requiring system Python) is deferred to a distribution
milestone, as the design suggests. `AGENT_KERNEL_CMD` is the override seam until then.

## Verification status

- **Verified live:** the `frontend/` UI, served by the kernel, driving a real
  conversation against LM Studio — streaming, a `write_file` tool call, the permission
  prompt (Allow), the tool result, and the final answer. This is M4's exit criterion
  (same session functionality as the CLI) exercised in the actual WebView content.
- **Authored to spec, not compiled here:** `src-tauri/` (the Rust shell). Building the
  native window needs `npm install` + `npm run tauri dev` on a machine with the Rust
  toolchain and WebView2. The shell is small and single-purpose (sidecar lifecycle only).

## Deferred to M5
- Toggleable read-only project/file viewer pane.
- Session persistence across restarts; exposing the kernel's own tools as an MCP server.
