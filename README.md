# agent-me

A general-purpose AI agent framework: one long-running **Python kernel** (agent loop,
provider abstraction, tool registry, hand-rolled MCP) with thin frontends — a **CLI**
REPL and, later, a **Tauri desktop app**.

See [DESIGN.md](DESIGN.md) for the full design and [AGENT.md](AGENT.md) for how the
agent works on this repo.

> **Status: M5 — all milestones complete.** Everything in M4 plus a read-only
> file/project viewer pane, session-persistence endpoints (sessions survive kernel
> restarts), and the kernel's own tools exposed as a hand-rolled **MCP server** for other
> clients. See DESIGN.md §7 and [desktop/README.md](desktop/README.md).

## Layout

```
src/
  agent_kernel/       # the kernel (long-running process)
    api/              # FastAPI HTTP/WS surface
    agent/            # provider-agnostic agent loop
    providers/        # provider adapters (Anthropic, OpenAI, LM Studio, Ollama)
    permissions.py    # tool risk levels + permission policy
    tools/            # tool registry + native tools (file/shell)
    mcp/              # hand-rolled MCP stdio client + manager   [server: M5]
    session/          # session store (file-based for now)
  agent_cli/          # REPL client over the kernel's WS API
desktop/              # Tauri desktop shell
  frontend/           # chat-first web UI (served by the kernel; bundled by Tauri)
  src-tauri/          # Rust shell: kernel sidecar lifecycle
tests/
```

## Quick start (M0)

```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -e .
cp .env.example .env        # then set ANTHROPIC_API_KEY

# terminal 1 — start the kernel
agent-kernel

# terminal 2 — start the REPL
agent
```

Prefer a window? The kernel also serves the chat UI at `http://127.0.0.1:8765/app/`
(open it in a browser), and the Tauri shell wraps that same UI — see
[desktop/README.md](desktop/README.md).

The exit criterion for M0: a real, token-streamed conversation with Claude through the
CLI.

### Switching providers

The provider is chosen entirely by `AGENT_PROVIDER`; nothing else in the kernel or CLI
changes. All four normalize into one internal streaming event format, so the agent loop,
tools, and MCP behave identically regardless of provider.

| `AGENT_PROVIDER` | Transport | Needs |
|---|---|---|
| `anthropic` | Anthropic SDK (SSE) | `ANTHROPIC_API_KEY` |
| `openai` | OpenAI `/chat/completions` (SSE) | `OPENAI_API_KEY` |
| `lmstudio` | OpenAI-compatible, local | [LM Studio](https://lmstudio.ai/) server + a model |
| `ollama` | native `/api/chat` (NDJSON) | [Ollama](https://ollama.com/) running + a pulled model |

`openai` and `lmstudio` share one hand-rolled OpenAI-compatible adapter; `ollama` has its
own NDJSON adapter. Example — run the loop against a free local model with LM Studio:

```
AGENT_PROVIDER=lmstudio
LMSTUDIO_MODEL=local-model
```

> LM Studio was added ahead of its planned M3 slot as a deliberate, documented deviation
> — see AGENT.md §4.

With LM Studio running, a live end-to-end smoke test spins up the kernel, streams a
conversation, and drives a real tool call over the WebSocket API:

```bash
python scripts/smoke_lmstudio.py --model google/gemma-4-12b-qat
```

Exit code 0 means the streaming path worked; the tool-call phase is reported (it warns
rather than fails if the model chooses not to call a tool).

## Tools & permissions

The agent has native tools: `read_file`, `list_dir` (read), `write_file` (write), and
`run_shell` (exec). Each declares a risk level. The permission policy
(`AGENT_TOOL_POLICY`) decides what happens:

- `ask` (default) — reads run automatically; writes and shell exec prompt for
  confirmation in the REPL before running.
- `allow` — auto-approve everything (headless runs).
- `deny` — refuse all non-read tools.

The kernel owns the policy; the frontend owns the confirmation UX (a REPL `[y/N]`
prompt now, a dialog in the Tauri app later). See DESIGN.md §8.

## MCP (hand-rolled)

The kernel speaks the Model Context Protocol as a client (written from scratch over a
stdio JSON-RPC transport). Connect a server at runtime and its tools are discovered and
folded into the registry — the agent then calls them just like native tools:

```bash
curl -X POST http://127.0.0.1:8765/mcp/connect -H 'content-type: application/json' \
  -d '{"name":"echo","command":"python","args":["tests/fixtures/mcp_echo_server.py"]}'
```

External MCP tools default to requiring confirmation (they're arbitrary); a server's
`readOnlyHint` annotation downgrades a tool to auto-allowed. A live end-to-end demo
(kernel + LM Studio + the bundled MCP server) is in `scripts/smoke_mcp.py`:

```bash
python scripts/smoke_mcp.py --model google/gemma-4-12b-qat
```

### As an MCP *server*

The kernel's own native tools are also exposed **to** other MCP clients (Claude Desktop,
another agent) over stdio:

```bash
agent-mcp-server        # or: python -m agent_kernel.mcp.server
```

By default it exposes only read-only tools (`read_file`, `list_dir`); set
`AGENT_MCP_EXPOSE_ALL=1` to also expose `write_file`/`run_shell` (trusted clients only).
Point any MCP client at the command above — e.g. in a client's server config:

```json
{ "command": "agent-mcp-server", "args": [] }
```

## API surface (kernel)

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/health` | liveness check |
| `POST` | `/session` | create a session |
| `WS`   | `/session/{id}/stream` | bidirectional streaming turn |
| `GET`  | `/tools` | list available tools (native + MCP) |
| `GET`  | `/sessions` | list persisted sessions (survive restarts) |
| `GET`  | `/session/{id}` | fetch a session's message history |
| `GET`  | `/files/tree` | list a workspace directory (read-only, sandboxed) |
| `GET`  | `/files/read` | read a workspace file (read-only, sandboxed) |
| `POST` | `/mcp/connect` | spawn a stdio MCP server and register its tools |
