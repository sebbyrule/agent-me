# AI Agent Framework — Design Document

## 1. Purpose & Scope

A general-purpose AI agent framework, similar in spirit to Claude Code / Hermes Agent, consisting of:

- A **Python kernel**: the agent loop, provider abstraction, tool registry, and a hand-rolled MCP client/server implementation.
- A **CLI**: an interactive REPL that talks to the kernel.
- A **Tauri desktop app**: a chat-first UI with a secondary project/file viewer pane (VS Code / Obsidian-style), sharing the same kernel process via a sidecar.

This is a **separate project** from the earlier kernel-architecture effort. That project is being set aside because it became difficult to work with — a driving design goal here is to avoid repeating that: build the smallest end-to-end loop first, prove it works, and only then add scope.

### Explicit non-goals (for now)
- Not building a full productivity suite (editor, git, messaging, etc.) — chat + minimal file viewer only.
- Not implementing the full MCP spec on day one — start with the subset needed to connect to one real server and expose one real tool.
- Not supporting OpenAI/Ollama until the Anthropic-only path works end-to-end (see §7, Sequencing).

---

## 2. Guiding Principles

1. **One kernel, two frontends.** CLI and desktop app are thin clients over the same running Python process. No logic is duplicated between them.
2. **Working loop over broad coverage.** A single provider, single tool, and single MCP server working reliably beats three providers half-working.
3. **Interface now, implementation later.** Abstractions (provider adapter, tool interface) are designed for multi-provider/multi-tool from the start, even though only one implementation ships early — this avoids a rewrite without over-building up front.
4. **Hand-rolled MCP is for learning.** Where the official SDK would be faster, that's fine to consult as reference, but the client/server implementation itself should be written from scratch to build real understanding of the protocol.
5. **Streaming-first.** Both the REPL and the chat UI need token-by-token streaming, not just request/response. This is a first-class requirement of the API layer, not an afterthought.

---

## 3. High-Level Architecture

```
┌─────────────┐         ┌──────────────────┐
│  CLI (REPL) │         │   Tauri App       │
│  Python     │         │   Rust shell      │
│  client     │         │   + WebView (UI)  │
└──────┬──────┘         └─────────┬─────────┘
       │                          │
       │     local HTTP/WS        │  (kernel spawned as sidecar process)
       └────────────┬─────────────┘
                     ▼
         ┌─────────────────────────┐
         │      Python Kernel        │
         │  (long-running process)   │
         │                            │
         │  - Agent loop              │
         │  - Provider adapter layer  │
         │  - Tool registry           │
         │  - MCP client              │
         │  - MCP server (exposes     │
         │    own tools externally)   │
         │  - Session store           │
         └─────────────────────────┘
```

**Why this shape:**
- The kernel owns all state and logic. It's a normal local server process (FastAPI + WebSocket), reachable at `localhost:<port>`.
- The CLI is a lightweight client — it renders the REPL and forwards input/output over the same API a UI would use.
- Tauri's Rust shell spawns the kernel as a **sidecar** on app launch and shuts it down on exit. The WebView frontend talks to it exactly like the CLI does — same endpoints, same message format.
- This means the desktop app doesn't get a second implementation of the agent loop — it's "just" a new frontend once the kernel is proven via the CLI.

---

## 4. Component Breakdown

### 4.1 Kernel (Python)

- **Agent loop** — orchestrates: receive user input → call provider → handle tool calls (including parallel tool calls) → return tool results → continue until a final response. Should be provider-agnostic at this layer.
- **Provider adapter layer** — a common interface (e.g. `send_message(messages, tools, stream=True) -> AsyncIterator[Event]`) that each provider implementation satisfies. Anthropic implemented first; OpenAI and Ollama slot in later without touching the agent loop.
- **Tool registry** — a registration system for tools (name, description, JSON schema, handler function). Handles both natively-defined tools and tools discovered dynamically via MCP.
- **MCP client** (hand-rolled) — connects to external MCP servers, performs discovery (`list_tools`), and invokes tools, translating results back into the tool registry's format.
- **MCP server** (hand-rolled) — exposes the kernel's own tools to *other* MCP clients (e.g., so this agent's tools could be used from Claude Desktop or another agent). This comes after the client side is working.
- **Session store** — persists conversation state (messages, tool call history) so sessions can survive kernel restarts. Start with local file-based (JSON/SQLite) storage; a database is not needed yet.
- **Local API layer** — FastAPI app exposing:
  - `POST /session` — create a session
  - `WS /session/{id}/stream` — bidirectional streaming for a conversation turn
  - `GET /tools` — list currently available tools (native + MCP-discovered)
  - `POST /mcp/connect` — register a new MCP server connection at runtime

### 4.2 CLI

- Interactive REPL (not just one-shot commands), similar in feel to Claude Code's terminal UI.
- Connects to the kernel's WebSocket endpoint, sends user input, renders streamed tokens and tool-call events as they arrive.
- Should support reconnecting to an existing session (kernel keeps running independently of any one client).

### 4.3 Tauri Desktop App

- **Shell**: Rust, manages kernel sidecar lifecycle (spawn on launch, health-check, graceful shutdown).
- **Frontend**: WebView-based UI, chat-first.
  - Primary pane: chat conversation with streaming responses, visible tool calls/results.
  - Secondary pane (toggleable): project/file viewer — read-only browsing to start (VS Code/Obsidian-style tree + preview), editing capability deferred.
- Talks to the kernel over the same local API contract as the CLI — no separate protocol.

---

## 5. Provider Abstraction

Even though only Anthropic ships first, the adapter interface should be designed against all three targets so the shape doesn't need to change later:

| Concern | Anthropic | OpenAI | Ollama |
|---|---|---|---|
| Streaming | SSE-based | SSE-based | HTTP streaming (NDJSON) |
| Tool calling | native tool_use blocks | function calling | model-dependent, varies by model |
| Parallel tool calls | supported | supported | inconsistent — needs guarding |

The adapter interface should normalize all three into one internal event stream format (e.g. `TextDelta`, `ToolCallStart`, `ToolCallResult`, `MessageComplete`) so the agent loop never branches on provider.

---

## 6. MCP Implementation Notes

Building this by hand (rather than using the official SDK) means budgeting real time for:
- Transport (stdio and/or HTTP+SSE, per the MCP spec)
- JSON-RPC message framing and correlation
- Capability negotiation / handshake
- Tool discovery and schema translation into the kernel's own tool format
- Error handling for misbehaving or slow external servers (timeouts, malformed responses)

Recommended approach: implement just enough of the client to talk to **one real, well-behaved MCP server** end-to-end before generalizing. This validates the protocol understanding without over-building against a spec that's easy to over-engineer for.

---

## 7. Sequencing / Milestones

**M0 — Kernel skeleton**
Python kernel process, local HTTP/WS API, Anthropic-only agent loop (no tools yet). Minimal CLI REPL connects and streams a plain conversation end-to-end.
*Exit criteria: you can have a real streamed conversation with Claude through the CLI.*

**M1 — Native tools**
Tool registry, a small number of hand-written tools (e.g. file read/write, shell exec). Agent loop handles tool calls and parallel tool calls.
*Exit criteria: agent can complete a task requiring at least one tool call, visible in the REPL.*

**M2 — MCP client**
Hand-rolled MCP client connects to one real external MCP server; its tools appear in the registry and are invokable by the agent loop identically to native tools.
*Exit criteria: agent completes a task using a tool sourced from an external MCP server.*

**M3 — Multi-provider**
Add OpenAI, then Ollama, behind the existing adapter interface.
*Exit criteria: same conversation/task can run against any of the three providers via a config switch.*

**M4 — Tauri shell**
Rust shell spawns kernel as sidecar; WebView chat UI hits the same API as the CLI.
*Exit criteria: same session-level functionality as the CLI, in a desktop window.*

**M5 — Desktop polish & MCP server**
File/project viewer pane; session persistence across restarts; expose the kernel's own tools as an MCP server for other clients to consume.

---

## 8. Open Questions (to revisit as you build)

- **Session storage format**: flat JSON files vs. SQLite — SQLite is probably worth it once you have multiple concurrent sessions, but JSON is fine for M0–M2.
- **Sidecar packaging**: how the Python kernel gets bundled/distributed with the Tauri app (PyInstaller vs. requiring a system Python) — decide this closer to M4, not now.
- **Auth/config for provider API keys**: local config file vs. OS keychain integration — fine to punt to M0 with a plain `.env`, revisit before any real distribution.
- **Tool permissions**: whether tool execution needs a confirmation step (especially shell/file tools) — worth deciding before M1 ships, since retrofitting a permission layer is more painful than designing it in.

---

## 9. Explicit Risks

- **Scope creep on providers**: the temptation to build all three providers at once was flagged early — resist it. M3 exists precisely so this doesn't block M0–M2.
- **MCP spec complexity**: hand-rolling MCP is valuable for learning but is the single biggest time-sink risk in this plan. Keep M2 scoped to "one server, one tool, working" before generalizing.
- **Kernel/UI coupling drift**: if the Tauri UI ever needs something the API doesn't expose, add it to the kernel's API — never let the UI reach into kernel internals directly, or the "one kernel, two frontends" principle breaks down.
