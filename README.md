# agent-me

A general-purpose AI agent framework: one long-running **Python kernel** (agent loop,
provider abstraction, tool registry, hand-rolled MCP) with thin frontends — a **CLI**
REPL and, later, a **Tauri desktop app**.

See [DESIGN.md](DESIGN.md) for the full design and [AGENT.md](AGENT.md) for how the
agent works on this repo.

> **Status: M1** — streaming agent loop with native tools (file read/write/list, shell
> exec), parallel tool calls, and a permission layer that confirms risky calls. Two
> provider adapters (Anthropic + LM Studio). MCP is next (M2). See DESIGN.md §7.

## Layout

```
src/
  agent_kernel/       # the kernel (long-running process)
    api/              # FastAPI HTTP/WS surface
    agent/            # provider-agnostic agent loop
    providers/        # provider adapters (Anthropic + LM Studio)
    permissions.py    # tool risk levels + permission policy
    tools/            # tool registry + native tools (file/shell)
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

## API surface (kernel)

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/health` | liveness check |
| `POST` | `/session` | create a session |
| `WS`   | `/session/{id}/stream` | bidirectional streaming turn |
| `GET`  | `/tools` | list available tools (native + MCP) |
| `POST` | `/mcp/connect` | register an MCP server at runtime (M2) |
