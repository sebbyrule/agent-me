# AGENT.md — Working Instructions

Operating instructions for the AI agent (me) working on this repository. Read this
first every session. The authoritative product spec is [DESIGN.md](DESIGN.md); this
file is *how I work*, not *what we're building*.

---

## 1. What this project is

A general-purpose AI agent framework: a **Python kernel** (agent loop + provider
abstraction + tool registry + hand-rolled MCP), a **CLI** REPL client, and a **Tauri
desktop app** — all thin frontends over one long-running kernel process.

**The prime directive** (from DESIGN.md §1): the earlier kernel effort was set aside
because it grew unwieldy. Do not repeat that. Build the **smallest end-to-end loop
first**, prove it works, and only then add scope.

## 2. Core principles I must honor

Pulled from DESIGN.md §2 — these override any instinct to be "thorough":

1. **One kernel, two frontends.** CLI and desktop are thin clients over the same
   kernel API. Never duplicate agent logic in a frontend. If a frontend needs
   something, add it to the kernel's API — never let a frontend reach into kernel
   internals.
2. **Working loop over broad coverage.** One provider, one tool, one MCP server
   working reliably beats three of each half-working.
3. **Interface now, implementation later.** Design abstractions (provider adapter,
   tool interface) for the multi-* future, but ship only one implementation early.
   Design the seam; don't build the whole house.
4. **Hand-rolled MCP is for learning.** Consult the official SDK as *reference* only;
   write the client/server from scratch.
5. **Streaming-first.** Token-by-token streaming is a first-class API requirement, not
   a later add-on.

## 3. Milestone discipline (DESIGN.md §7)

Work strictly in order. **Do not start a milestone until the previous one's exit
criteria are met and demonstrated.**

| Milestone | Deliverable | Exit criteria |
|---|---|---|
| **M0** | Kernel skeleton + HTTP/WS API + Anthropic-only loop (no tools) + minimal CLI REPL | A real streamed conversation with Claude through the CLI |
| **M1** | Tool registry + a few native tools; parallel tool calls | Agent completes a task needing ≥1 tool call, visible in REPL |
| **M2** | Hand-rolled MCP client → one real external server | Agent completes a task using an MCP-sourced tool |
| **M3** | OpenAI then Ollama behind the adapter | Same task runs against any provider via config switch |
| **M4** | Tauri shell spawns kernel as sidecar; WebView chat UI | Same session functionality as CLI, in a desktop window |
| **M5** | File viewer pane; session persistence across restarts; kernel as MCP *server* | — |

**We are currently at: M0.**

## 4. Anti-scope-creep rules (DESIGN.md §9)

- **Providers:** Do NOT touch OpenAI/Ollama until M3. Anthropic only.
- **MCP:** Keep M2 to "one server, one tool, working." The spec is a time-sink; resist
  generalizing early.
- **No UI reaching into internals:** enforce the API boundary at all times.
- When tempted to add breadth, stop and ask: *does the current milestone's exit
  criterion need this?* If no, it waits.

## 5. Open decisions to respect (DESIGN.md §8)

- Session storage: flat JSON is fine for M0–M2; revisit SQLite when concurrent
  sessions appear.
- Provider API keys: plain `.env` for now (never commit it). OS keychain later.
- **Tool permissions:** decide the confirmation-step design *before M1 ships* — a
  permission layer is painful to retrofit around shell/file tools.
- Sidecar packaging: decide near M4, not now.

## 6. How I build

- **Python:** target 3.14 (installed). `src/` layout, type hints, `async`/`await`
  throughout the kernel (FastAPI + WebSockets). Keep modules small and single-purpose.
- **Env/config:** load from `.env` via the config module. Never hardcode secrets;
  never print API keys.
- **Dependencies:** add only what the current milestone needs. Prefer the standard
  library where reasonable (especially for hand-rolled MCP).
- **Run/verify before claiming done:** actually start the kernel and CLI and confirm
  behavior. If something is unverified, say so plainly.
- **Match surrounding style.** Read a neighboring file before adding one.

## 7. Testing

- Add tests alongside features that have non-trivial logic (event normalization,
  tool-schema translation, session store). Don't chase coverage on glue code.
- A milestone isn't "done" until its exit criterion is demonstrated end-to-end, not
  just when unit tests pass.

## 8. Git best practices (follow every time)

**Branch → build → verify → merge → commit stays on main.** Never develop directly on
`main`.

1. **Start from a clean, up-to-date `main`:**
   ```bash
   git checkout main
   git status          # confirm clean
   ```
2. **Create a feature branch** named for the work — `feature/<slug>`, `fix/<slug>`, or
   `chore/<slug>`. One branch per logical unit of work (roughly one milestone or one
   coherent feature):
   ```bash
   git checkout -b feature/m0-kernel-skeleton
   ```
3. **Commit in small, logical steps** as the work progresses. Write imperative,
   present-tense messages that explain *why*, not just *what*:
   ```
   Add Anthropic streaming adapter behind provider interface

   Normalizes SSE events into the internal TextDelta/MessageComplete
   stream so the agent loop stays provider-agnostic (DESIGN.md §5).
   ```
4. **Verify the feature actually works** before merging — run the kernel + CLI, hit the
   milestone's exit criterion. Do not merge broken or unverified code.
5. **Merge to `main` only once it works:**
   ```bash
   git checkout main
   git merge --no-ff feature/m0-kernel-skeleton
   ```
   Use `--no-ff` so each feature stays a visible unit in history.
6. **Delete the merged branch:**
   ```bash
   git branch -d feature/m0-kernel-skeleton
   ```
7. **Push only when the user asks.** Do not push, force-push, or create PRs unprompted.

**Rules of thumb**
- Commit or merge only when the user has asked me to, or when it's the natural close of
  a unit of work I was told to do — but always land finished work on `main` via the
  branch flow above.
- Never commit secrets, `.env`, virtualenvs, build artifacts, or `node_modules`
  (`.gitignore` covers these — keep it current).
- Keep `main` releasable: it should always at least import and start.
- Never use `git push --force`, `git reset --hard`, or history rewrites on shared
  branches without explicit instruction.
- End commit messages with the required trailer:
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  ```

## 9. Session start checklist

1. Re-read this file and DESIGN.md's §7 milestone table.
2. Confirm which milestone is active (§3 above) and its exit criterion.
3. `git status` / `git branch` — know where I am before changing anything.
4. Do the smallest next thing that moves the active milestone toward its exit
   criterion. Nothing from a later milestone.
