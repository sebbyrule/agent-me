// agent-me chat UI — a thin client over the kernel's HTTP/WS API (DESIGN.md
// §4.2/§4.3). Holds no agent logic: create a session, open the streaming
// WebSocket, render the normalized event stream. Works both when served by the
// kernel (same origin) and when bundled in Tauri (a tauri:// origin), by
// resolving the kernel base URL from the current location with a localhost
// fallback.

const KERNEL =
  location.protocol.startsWith("http") && location.host
    ? location.origin
    : "http://127.0.0.1:8765";
const WS_BASE = KERNEL.replace(/^http/, "ws");

const el = (id) => document.getElementById(id);
const log = el("log");
const input = el("input");
const sendBtn = el("send");
const dot = el("dot");
const providerLabel = el("provider");

let ws = null;
let sessionId = null;
let currentBot = null; // the assistant bubble being streamed into

function setStatus(state, title) {
  dot.className = "dot dot--" + state;
  dot.title = title;
}

function clearEmpty() {
  const empty = el("empty");
  if (empty) empty.remove();
}

function scroll() {
  log.scrollTop = log.scrollHeight;
}

function addUser(text) {
  clearEmpty();
  const div = document.createElement("div");
  div.className = "msg msg--user";
  div.textContent = text;
  log.appendChild(div);
  scroll();
}

function botBubble() {
  if (!currentBot) {
    currentBot = document.createElement("div");
    currentBot.className = "msg msg--bot cursor";
    log.appendChild(currentBot);
  }
  return currentBot;
}

function addError(message) {
  const div = document.createElement("div");
  div.className = "msg msg--error";
  div.textContent = "⚠ " + message;
  log.appendChild(div);
  scroll();
}

function addToolCall(event) {
  currentBot = null; // a tool call ends the current text run
  const div = document.createElement("div");
  div.className = "tool";
  div.dataset.id = event.id;
  const args = JSON.stringify(event.arguments || {});
  div.innerHTML =
    `⚙ <span class="name"></span><span class="args"></span>`;
  div.querySelector(".name").textContent = event.name;
  div.querySelector(".args").textContent = `(${args})`;
  log.appendChild(div);
  scroll();
}

function addToolResult(event) {
  const chip = [...log.querySelectorAll(".tool")].reverse().find(
    (t) => t.dataset.id === event.id && !t.dataset.done
  );
  const target = chip || log.appendChild(document.createElement("div"));
  if (!chip) target.className = "tool";
  target.dataset.done = "1";
  const res = document.createElement("div");
  res.className = "result" + (event.is_error ? " result--error" : "");
  res.textContent = (event.is_error ? "✗ " : "→ ") + shorten(event.result);
  target.appendChild(res);
  scroll();
}

function shorten(value, limit = 600) {
  let text = typeof value === "string" ? value : JSON.stringify(value);
  if (text && text.length > limit) text = text.slice(0, limit) + "…";
  return text;
}

function addPermission(event) {
  currentBot = null;
  const div = document.createElement("div");
  div.className = "perm";
  const args = JSON.stringify(event.arguments || {});
  div.innerHTML = `
    <div class="q">Allow <b>${event.risk}</b> tool <code>${event.name}(${escapeHtml(
      args
    )})</code>?</div>
    <div class="actions">
      <button class="allow">Allow</button>
      <button class="deny">Deny</button>
    </div>`;
  const finish = (approved) => {
    div.querySelectorAll("button").forEach((b) => (b.disabled = true));
    div.querySelector(".q").insertAdjacentText(
      "beforeend",
      approved ? "  ✓ allowed" : "  ✗ denied"
    );
    ws.send(JSON.stringify({ id: event.id, approved }));
  };
  div.querySelector(".allow").onclick = () => finish(true);
  div.querySelector(".deny").onclick = () => finish(false);
  log.appendChild(div);
  scroll();
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function onEvent(event) {
  switch (event.type) {
    case "text_delta":
      botBubble().textContent += event.text;
      scroll();
      break;
    case "tool_call_start":
      addToolCall(event);
      break;
    case "tool_call_result":
      addToolResult(event);
      break;
    case "permission_request":
      addPermission(event);
      break;
    case "message_complete":
      if (currentBot) currentBot.classList.remove("cursor");
      currentBot = null;
      break;
    case "turn_complete":
      if (currentBot) currentBot.classList.remove("cursor");
      currentBot = null;
      setInputEnabled(true);
      break;
    case "error":
      addError(event.message);
      if (currentBot) currentBot.classList.remove("cursor");
      currentBot = null;
      setInputEnabled(true);
      break;
  }
}

function setInputEnabled(enabled) {
  input.disabled = !enabled;
  sendBtn.disabled = !enabled;
  if (enabled) input.focus();
}

function send() {
  const text = input.value.trim();
  if (!text || input.disabled || !ws || ws.readyState !== WebSocket.OPEN) return;
  addUser(text);
  input.value = "";
  autosize();
  setInputEnabled(false);
  ws.send(JSON.stringify({ input: text }));
}

async function boot() {
  try {
    const health = await (await fetch(`${KERNEL}/health`)).json();
    providerLabel.textContent = health.provider || "?";
  } catch (e) {
    providerLabel.textContent = "offline";
  }

  try {
    const res = await fetch(`${KERNEL}/session`, { method: "POST" });
    sessionId = (await res.json()).id;
  } catch (e) {
    setStatus("bad", "cannot reach kernel");
    addError(`Cannot reach the kernel at ${KERNEL}. Is agent-kernel running?`);
    return;
  }

  ws = new WebSocket(`${WS_BASE}/session/${sessionId}/stream`);
  ws.onopen = () => {
    setStatus("ok", "connected");
    setInputEnabled(true);
  };
  ws.onclose = () => {
    setStatus("bad", "disconnected");
    setInputEnabled(false);
  };
  ws.onerror = () => setStatus("bad", "connection error");
  ws.onmessage = (msg) => onEvent(JSON.parse(msg.data));
}

function autosize() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
}

el("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  send();
});
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});
input.addEventListener("input", autosize);

boot();
