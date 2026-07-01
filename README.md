# agent-me

A general-purpose AI agent framework: one long-running **Python kernel** (agent loop,
provider abstraction, tool registry, hand-rolled MCP) with thin frontends — a **CLI**
REPL and, later, a **Tauri desktop app**.

See [DESIGN.md](DESIGN.md) for the full design and [AGENT.md](AGENT.md) for how the
agent works on this repo.

> **Status: M2** — everything in M1 plus a hand-rolled MCP client: connect a stdio MCP
> server at runtime (`POST /mcp/connect`) and its tools join the registry, invokable by
> the agent exactly like native tools. Two provider adapters (Anthropic + LM Studio).
> Multi-provider config switch (M3) is next. See DESIGN.md §7.

## Layout

```
src/
  agent_kernel/       # the kernel (long-running process)
    api/              # FastAPI HTTP/WS surface
    agent/            # provider-agnostic agent loop
    providers/        # provider adapters (Anthropic + LM Studio)
    permissions.py    # tool risk levels + permission policy
    tools/            # tool registry + native tools (file/shell)
    mcp/              # hand-rolled MCP stdio client + manager   [server: M5]
    session/          # session store (file-based for now)
  agent_cli/          # REPL client over the kernel's WS API
desktop/              # Tauri app                                [M4]
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

The exit criterion for M0: a real, token-streamed conversation with Claude through the
CLI.

### Using LM Studio instead of Anthropic

A second provider adapter targets [LM Studio](https://lmstudio.ai/)'s local
OpenAI-compatible server, so you can run the loop against a local model for free (great
for testing without spending Anthropic tokens). Start LM Studio's server, load a model,
then in `.env`:

```
AGENT_PROVIDER=lmstudio
LMSTUDIO_BASE_URL=http://localhost:1234/v1
LMSTUDIO_MODEL=local-model
```

The provider is chosen by `AGENT_PROVIDER`; nothing else in the kernel or CLI changes.
> This adapter was added ahead of its planned M3 slot as a deliberate, documented
> deviation — see AGENT.md §4.

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

## API surface (kernel)

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/health` | liveness check |
| `POST` | `/session` | create a session |
| `WS`   | `/session/{id}/stream` | bidirectional streaming turn |
| `GET`  | `/tools` | list available tools (native + MCP) |
| `POST` | `/mcp/connect` | spawn a stdio MCP server and register its tools |
