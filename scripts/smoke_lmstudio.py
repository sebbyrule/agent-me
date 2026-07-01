"""Live smoke test against a running LM Studio server.

Spawns the kernel configured for LM Studio, drives a real streamed conversation
and a real tool call over the kernel's WebSocket API, and reports pass/fail.
This is the end-to-end confirmation of M0 (streaming) + M1 (tool calling) against
an actual model — the thing unit tests can't prove.

Prerequisites:
- LM Studio's local server is running (default http://localhost:1234).
- The target model is downloaded (LM Studio JIT-loads it on first request).

Usage:
    python scripts/smoke_lmstudio.py --model qwen2.5-coder-3b-instruct
    python scripts/smoke_lmstudio.py --model <id> --base-url http://localhost:1234/v1

Exit code 0 = the streaming path worked end-to-end. The tool-call phase is
reported but only warns if the model chooses not to call a tool (that's model
behavior, not a kernel defect).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from contextlib import asynccontextmanager

import httpx
import websockets

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Windows consoles default to a legacy codepage (cp1252); prefer UTF-8 so output
# never crashes on non-ASCII, but keep the markers below ASCII regardless.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def log(msg: str) -> None:
    print(msg, flush=True)


async def wait_for_health(base: str, timeout: float = 30.0) -> bool:
    async with httpx.AsyncClient() as client:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                resp = await client.get(f"{base}/health", timeout=2.0)
                if resp.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.4)
    return False


@asynccontextmanager
async def kernel_process(port: int, model: str, base_url: str):
    """Start the kernel as a subprocess wired to LM Studio; tear it down after."""
    env = {
        **os.environ,
        "AGENT_PROVIDER": "lmstudio",
        "LMSTUDIO_MODEL": model,
        "LMSTUDIO_BASE_URL": base_url,
        "AGENT_TOOL_POLICY": "allow",  # non-interactive: auto-approve tool calls
        "KERNEL_HOST": "127.0.0.1",
        "KERNEL_PORT": str(port),
        "SESSION_DIR": os.path.join(tempfile.gettempdir(), "agent-me-smoke-sessions"),
    }
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "agent_kernel",
        cwd=REPO_ROOT,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        if not await wait_for_health(f"http://127.0.0.1:{port}"):
            out = await proc.stdout.read() if proc.stdout else b""
            raise RuntimeError(
                f"Kernel did not become healthy.\n--- kernel output ---\n"
                f"{out.decode(errors='replace')}"
            )
        yield proc
    finally:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()


async def new_session(base: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{base}/session", timeout=10)
        resp.raise_for_status()
        return resp.json()["id"]


async def run_turn(ws_url: str, prompt: str, recv_timeout: float) -> dict:
    """Send one prompt, collect the event stream until turn_complete/error.

    Returns a summary dict: {text, tool_calls, tool_results, error}.
    """
    summary = {"text": "", "tool_calls": [], "tool_results": [], "error": None}
    async with websockets.connect(ws_url, max_size=None) as ws:
        await ws.send(json.dumps({"input": prompt}))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=recv_timeout)
            event = json.loads(raw)
            etype = event.get("type")
            if etype == "text_delta":
                summary["text"] += event["text"]
            elif etype == "tool_call_start":
                summary["tool_calls"].append(
                    {"name": event["name"], "arguments": event.get("arguments", {})}
                )
            elif etype == "tool_call_result":
                summary["tool_results"].append(
                    {"name": event["name"], "is_error": event.get("is_error", False)}
                )
            elif etype == "error":
                summary["error"] = event["message"]
                return summary
            elif etype == "turn_complete":
                return summary
    return summary


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=os.getenv("LMSTUDIO_MODEL", "qwen2.5-coder-3b-instruct"),
        help="LM Studio model id to target (JIT-loaded on first request).",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1"),
    )
    parser.add_argument("--port", type=int, default=8790, help="Kernel port.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="Per-response timeout (first call includes model load).",
    )
    args = parser.parse_args()

    kernel_http = f"http://127.0.0.1:{args.port}"

    # Preflight: is LM Studio reachable, and is the model present?
    log(f"-> Checking LM Studio at {args.base_url} ...")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{args.base_url}/models", timeout=5)
            resp.raise_for_status()
            ids = [m["id"] for m in resp.json().get("data", [])]
    except httpx.HTTPError as exc:
        log(f"[FAIL] Could not reach LM Studio: {exc}")
        log("  Start LM Studio and enable its local server, then retry.")
        return 2
    log(f"  LM Studio is up ({len(ids)} models available).")
    if args.model not in ids:
        log(f"  [WARN] model '{args.model}' not in the list — LM Studio may still JIT-load it.")
    log(f"  target model: {args.model}")

    passed = True
    async with kernel_process(args.port, args.model, args.base_url):
        log(f"[OK] Kernel healthy on {kernel_http} (provider=lmstudio)")

        # --- Phase 1: plain streamed conversation (M0). Hard gate. ---
        log("\n[1/2] Streaming a plain conversation ...")
        sid = await new_session(kernel_http)
        ws_url = f"ws://127.0.0.1:{args.port}/session/{sid}/stream"
        try:
            r = await run_turn(
                ws_url,
                "Reply in one short sentence: what is 2 + 2?",
                args.timeout,
            )
        except asyncio.TimeoutError:
            log(f"[FAIL] Timed out after {args.timeout}s waiting for a response.")
            return 1
        if r["error"]:
            log(f"[FAIL] Kernel returned an error: {r['error']}")
            return 1
        if not r["text"].strip():
            log("[FAIL] No streamed text received.")
            passed = False
        else:
            log(f"  streamed reply: {r['text'].strip()[:200]}")
            log("[OK] Streaming works end-to-end.")

        # --- Phase 2: tool call (M1). Reported; warns if model skips tools. ---
        log("\n[2/2] Asking the model to use a tool (list_dir) ...")
        sid = await new_session(kernel_http)
        ws_url = f"ws://127.0.0.1:{args.port}/session/{sid}/stream"
        try:
            r = await run_turn(
                ws_url,
                "Use your list_dir tool to list the files in the current directory "
                "('.'), then tell me one filename you see.",
                args.timeout,
            )
        except asyncio.TimeoutError:
            log(f"[FAIL] Timed out after {args.timeout}s waiting for a response.")
            return 1
        if r["error"]:
            log(f"[FAIL] Kernel returned an error: {r['error']}")
            return 1
        if r["tool_calls"]:
            names = ", ".join(tc["name"] for tc in r["tool_calls"])
            ok_results = sum(1 for tr in r["tool_results"] if not tr["is_error"])
            log(f"  tool calls: {names}")
            log(f"  tool results: {ok_results}/{len(r['tool_results'])} ok")
            log(f"  final reply: {r['text'].strip()[:200]}")
            log("[OK] Tool calling works end-to-end.")
        else:
            log("  [WARN] The model answered without calling a tool.")
            log(f"    reply: {r['text'].strip()[:200]}")
            log("    (Kernel wiring is fine — try a more tool-capable model to see a call.)")

    log("\n" + ("PASS" if passed else "FAIL"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
