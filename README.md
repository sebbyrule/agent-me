# agent-me

A general-purpose AI agent framework: one long-running **Python kernel** (agent loop,
provider abstraction, tool registry, hand-rolled MCP) with thin frontends — a **CLI**
REPL and, later, a **Tauri desktop app**.

See [DESIGN.md](DESIGN.md) for the full design and [AGENT.md](AGENT.md) for how the
agent works on this repo.

> **Status: M0** — kernel skeleton with an Anthropic-only streaming loop and a minimal
> CLI REPL. No tools or MCP yet (those are M1/M2). See DESIGN.md §7 for the roadmap.

## Layout

```
src/
  agent_kernel/       # the kernel (long-running process)
    api/              # FastAPI HTTP/WS surface
    agent/            # provider-agnostic agent loop
    providers/        # provider adapters (Anthropic only for now)
    tools/            # tool registry (native + MCP-discovered)  [grows in M1]
    mcp/              # hand-rolled MCP client/server            [grows in M2/M5]
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

## API surface (kernel)

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/health` | liveness check |
| `POST` | `/session` | create a session |
| `WS`   | `/session/{id}/stream` | bidirectional streaming turn |
| `GET`  | `/tools` | list available tools (native + MCP) |
| `POST` | `/mcp/connect` | register an MCP server at runtime (M2) |
