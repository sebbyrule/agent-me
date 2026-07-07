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
const providerSelect = el("providerSelect");
const modelInput = el("modelInput");

let ws = null;
let sessionId = null;
let currentBot = null; // the assistant bubble being streamed into
let connected = false;
let turnActive = false; // a turn is streaming (Send becomes Stop)

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

// Minimal, escape-first Markdown -> HTML for assistant messages. Handles fenced
// code blocks, inline code, bold/italic, links, headings, and lists. All source
// is HTML-escaped before any markup is added (LLM output is untrusted), and
// links are restricted to http(s).
function renderMarkdown(src) {
  // Split on fenced code blocks (kept via a capturing group), render each part.
  const parts = src.split(/(```[\w+-]*\n?[\s\S]*?```)/g);
  let out = "";
  for (const part of parts) {
    if (!part) continue;
    const fence = part.match(/^```([\w+-]*)\n?([\s\S]*?)```$/);
    if (fence) {
      const cls = fence[1] ? ` class="lang-${fence[1]}"` : "";
      out += `<pre class="code"><code${cls}>${escapeHtml(fence[2].replace(/\n$/, ""))}</code></pre>`;
    } else {
      out += renderInline(part);
    }
  }
  return out;
}

// Escape + inline spans + block structure for non-code Markdown text.
function renderInline(src) {
  let text = escapeHtml(src);
  text = text.replace(/`([^`]+)`/g, (_m, c) => `<code>${c}</code>`);
  text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  text = text.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  text = text.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener">$1</a>'
  );
  let html = "";
  let list = null;
  const closeList = () => {
    if (list) {
      html += `</${list}>`;
      list = null;
    }
  };
  for (const line of text.split("\n")) {
    let m;
    if ((m = line.match(/^(#{1,3})\s+(.*)$/))) {
      closeList();
      const lvl = m[1].length + 2;
      html += `<h${lvl}>${m[2]}</h${lvl}>`;
    } else if ((m = line.match(/^\s*[-*]\s+(.*)$/))) {
      if (list !== "ul") { closeList(); html += "<ul>"; list = "ul"; }
      html += `<li>${m[1]}</li>`;
    } else if ((m = line.match(/^\s*\d+\.\s+(.*)$/))) {
      if (list !== "ol") { closeList(); html += "<ol>"; list = "ol"; }
      html += `<li>${m[1]}</li>`;
    } else if (line.trim() === "") {
      closeList();
    } else {
      closeList();
      html += `<p>${line}</p>`;
    }
  }
  closeList();
  return html;
}

// Dependency-free syntax highlighting, applied to completed code blocks.
const HL_KEYWORDS = {
  python: "def class return import from as if elif else for while in try except finally with lambda yield await async pass break continue raise global nonlocal and or not is del assert None True False",
  javascript: "function return const let var if else for while do switch case break continue new class extends super this typeof instanceof await async yield import export from default try catch finally throw delete in of void null undefined true false",
  json: "true false null",
  bash: "if then else elif fi for while do done case esac function in return export local echo",
  rust: "fn let mut const struct enum impl trait pub use mod match if else for while loop return self as in ref move async await dyn where true false",
  go: "func var const type struct interface package import if else for range return go defer chan map switch case default nil true false",
};
const HL_ALIAS = { js: "javascript", ts: "javascript", jsx: "javascript", tsx: "javascript", py: "python", sh: "bash", shell: "bash", zsh: "bash", rs: "rust", golang: "go" };

function highlightCode(code, lang) {
  lang = (HL_ALIAS[lang] || lang || "").toLowerCase();
  const kw = new Set((HL_KEYWORDS[lang] || "").split(/\s+/).filter(Boolean));
  // One regex literal (single-backslash escapes only) with classifying groups:
  // 1=comment, 2=string, 3=number, 4=identifier.
  const re = /(\/\/[^\n]*|\/\*[\s\S]*?\*\/|#[^\n]*)|("[^"\n]*"|'[^'\n]*'|`[^`]*`)|(\b\d[\d_]*(?:\.\d+)?\b)|([A-Za-z_$][\w$]*)/g;
  let out = "";
  let last = 0;
  let m;
  while ((m = re.exec(code)) !== null) {
    out += escapeHtml(code.slice(last, m.index));
    const tok = m[0];
    let cls = null;
    if (m[1]) cls = "tok-comment";
    else if (m[2]) cls = "tok-string";
    else if (m[3]) cls = "tok-number";
    else if (m[4] && kw.has(tok)) cls = "tok-keyword";
    out += cls ? `<span class="${cls}">${escapeHtml(tok)}</span>` : escapeHtml(tok);
    last = m.index + tok.length;
  }
  out += escapeHtml(code.slice(last));
  return out;
}

function highlightCodeBlocks(root) {
  root.querySelectorAll("pre.code > code").forEach((code) => {
    if (code.dataset.hl) return;
    const lang = (code.className.match(/lang-([\w+-]*)/) || [])[1] || "";
    code.innerHTML = highlightCode(code.textContent, lang);
    code.dataset.hl = "1";
  });
}

// Add a hover Copy button to each code block (copies the raw code text).
function addCopyButtons(root) {
  root.querySelectorAll("pre.code").forEach((pre) => {
    if (pre.dataset.copy) return;
    pre.dataset.copy = "1";
    const btn = document.createElement("button");
    btn.className = "copy-btn";
    btn.type = "button";
    btn.textContent = "Copy";
    btn.addEventListener("click", async () => {
      const code = pre.querySelector("code");
      const text = code ? code.textContent : "";
      let ok = false;
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(text);
          ok = true;
        }
      } catch (e) {
        ok = false;
      }
      if (!ok) {
        // Fallback for non-secure contexts / no clipboard permission.
        try {
          const ta = document.createElement("textarea");
          ta.value = text;
          ta.style.position = "fixed";
          ta.style.opacity = "0";
          document.body.appendChild(ta);
          ta.select();
          ok = document.execCommand("copy");
          document.body.removeChild(ta);
        } catch (e) {
          ok = false;
        }
      }
      btn.textContent = ok ? "Copied" : "Failed";
      setTimeout(() => (btn.textContent = "Copy"), 1200);
    });
    pre.appendChild(btn);
  });
}

function onEvent(event) {
  switch (event.type) {
    case "text_delta": {
      const bubble = botBubble();
      bubble._raw = (bubble._raw || "") + event.text;
      bubble.innerHTML = renderMarkdown(bubble._raw);
      scroll();
      break;
    }
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
      highlightCodeBlocks(log);
      addCopyButtons(log);
      currentBot = null;
      break;
    case "turn_complete":
      endTurn();
      refreshChatsIfOpen(); // message counts / a new session may have appeared
      break;
    case "cancelled":
      endTurn();
      break;
    case "error":
      addError(event.message);
      endTurn();
      break;
  }
}

function updateComposer() {
  if (!connected) {
    input.disabled = true;
    sendBtn.disabled = true;
    sendBtn.textContent = "Send";
    sendBtn.classList.remove("stop");
    return;
  }
  input.disabled = turnActive;
  sendBtn.disabled = false;
  sendBtn.textContent = turnActive ? "Stop" : "Send";
  sendBtn.classList.toggle("stop", turnActive);
  if (!turnActive) input.focus();
}

function endTurn() {
  turnActive = false;
  if (currentBot) currentBot.classList.remove("cursor");
  currentBot = null;
  updateComposer();
}

async function send() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  if (turnActive) {
    ws.send(JSON.stringify({ cancel: true })); // Send button acts as Stop
    return;
  }
  const text = input.value.trim();
  if (!text) return;
  hideMenu();
  addUser(text);
  input.value = "";
  autosize();
  turnActive = true;
  updateComposer();
  const expanded = await expandMentions(text);
  ws.send(JSON.stringify({ input: expanded }));
}

async function loadProviders() {
  try {
    const data = await (await fetch(`${KERNEL}/providers`)).json();
    providerSelect.innerHTML = "";
    for (const p of data.providers) {
      const opt = document.createElement("option");
      opt.value = p;
      opt.textContent = p;
      if (p === data.current) opt.selected = true;
      providerSelect.appendChild(opt);
    }
    modelInput.value = data.model || "";
  } catch (e) {
    providerSelect.innerHTML = "<option>offline</option>";
  }
}

async function setProvider(body) {
  try {
    const res = await fetch(`${KERNEL}/provider`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (data.current) {
      providerSelect.value = data.current;
      modelInput.value = data.model || "";
    }
  } catch (e) {
    /* ignore */
  }
}

async function boot() {
  await loadProviders();

  try {
    const res = await fetch(`${KERNEL}/session`, { method: "POST" });
    sessionId = (await res.json()).id;
  } catch (e) {
    setStatus("bad", "cannot reach kernel");
    addError(`Cannot reach the kernel at ${KERNEL}. Is agent-kernel running?`);
    return;
  }

  connect();
}

function connect() {
  if (ws) {
    try { ws.close(); } catch (e) { /* ignore */ }
  }
  ws = new WebSocket(`${WS_BASE}/session/${sessionId}/stream`);
  ws.onopen = () => {
    connected = true;
    setStatus("ok", "connected");
    updateComposer();
  };
  ws.onclose = () => {
    connected = false;
    turnActive = false;
    setStatus("bad", "disconnected");
    updateComposer();
  };
  ws.onerror = () => setStatus("bad", "connection error");
  ws.onmessage = (msg) => onEvent(JSON.parse(msg.data));
}

// --- Conversations: surfaces the /sessions and /session/{id} endpoints -------

function clearLog() {
  log.innerHTML = "";
  currentBot = null;
}

function appendBot(text) {
  const div = document.createElement("div");
  div.className = "msg msg--bot";
  div.innerHTML = renderMarkdown(text);
  highlightCodeBlocks(div);
  addCopyButtons(div);
  log.appendChild(div);
}

function renderHistory(messages) {
  clearLog();
  for (const m of messages) {
    if (m.role === "user") {
      addUser(typeof m.content === "string" ? m.content : JSON.stringify(m.content));
    } else if (m.role === "assistant") {
      if (m.content) appendBot(m.content);
      for (const tc of m.tool_calls || []) {
        addToolCall({ id: tc.id, name: tc.name, arguments: tc.arguments });
      }
    } else if (m.role === "tool") {
      for (const r of m.tool_results || []) {
        addToolResult({ id: r.id, name: r.name, result: r.result, is_error: r.is_error });
      }
    }
  }
  currentBot = null;
  scroll();
}

async function loadChats() {
  let sessions = [];
  try {
    sessions = (await (await fetch(`${KERNEL}/sessions`)).json()).sessions || [];
  } catch (e) {
    return;
  }
  const box = el("chats");
  box.innerHTML = "";
  if (!sessions.length) {
    box.innerHTML = '<div class="none">No conversations yet.</div>';
    return;
  }
  for (const s of sessions) {
    const item = document.createElement("div");
    item.className = "chat-item" + (s.id === sessionId ? " active" : "");
    item.dataset.id = s.id;
    item.innerHTML = `<span class="cid"></span><span class="cnt"></span>`;
    item.querySelector(".cid").textContent = s.id.slice(0, 8);
    item.querySelector(".cnt").textContent = s.messages + " msg";
    item.addEventListener("click", () => selectSession(s.id));
    box.appendChild(item);
  }
}

async function selectSession(id) {
  if (id === sessionId && ws && ws.readyState === WebSocket.OPEN) return;
  sessionId = id;
  try {
    const data = await (await fetch(`${KERNEL}/session/${id}`)).json();
    renderHistory(data.messages || []);
  } catch (e) {
    clearLog();
  }
  connect();
  markActiveChat(id);
}

async function newChat() {
  try {
    const res = await fetch(`${KERNEL}/session`, { method: "POST" });
    sessionId = (await res.json()).id;
  } catch (e) {
    addError("Could not create a new conversation.");
    return;
  }
  clearLog();
  connect();
  loadChats();
}

function markActiveChat(id) {
  document
    .querySelectorAll("#chats .chat-item")
    .forEach((n) => n.classList.toggle("active", n.dataset.id === id));
}

function refreshChatsIfOpen() {
  const sb = document.getElementById("sidebar");
  if (sb && !sb.classList.contains("hidden")) loadChats();
}

function autosize() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
}

// --- File viewer pane (M5) — read-only tree + preview over /files/* -------

const sidebar = el("sidebar");
const tree = el("tree");
const preview = el("preview");
let treeLoaded = false;

el("sidebarToggle").addEventListener("click", () => {
  const showing = sidebar.classList.toggle("hidden") === false;
  el("sidebarToggle").classList.toggle("active", showing);
  if (showing) {
    loadChats();
    if (!treeLoaded) {
      treeLoaded = true;
      loadDir("", tree, 0);
    }
  }
});

el("newChat").addEventListener("click", newChat);

providerSelect.addEventListener("change", () => setProvider({ provider: providerSelect.value }));
modelInput.addEventListener("change", () => setProvider({ model: modelInput.value.trim() }));

async function loadDir(path, container, depth) {
  try {
    const res = await fetch(`${KERNEL}/files/tree?path=${encodeURIComponent(path)}`);
    const data = await res.json();
    for (const entry of data.entries) {
      container.appendChild(entry.type === "dir" ? dirNode(entry, depth) : fileNode(entry, depth));
    }
  } catch (e) {
    /* ignore tree errors */
  }
}

function rowPad(depth) {
  return 8 + depth * 14;
}

function dirNode(entry, depth) {
  const wrap = document.createElement("div");
  const row = document.createElement("div");
  row.className = "node";
  row.style.paddingLeft = rowPad(depth) + "px";
  row.innerHTML = `<span class="twist">▸</span><span class="icon icon--dir">▉</span><span class="label"></span>`;
  row.querySelector(".label").textContent = entry.name;
  const children = document.createElement("div");
  children.className = "children";
  children.style.display = "none";
  let loaded = false;
  row.addEventListener("click", () => {
    const open = children.style.display === "none";
    children.style.display = open ? "block" : "none";
    row.querySelector(".twist").textContent = open ? "▾" : "▸";
    if (open && !loaded) {
      loaded = true;
      loadDir(entry.path, children, depth + 1);
    }
  });
  wrap.appendChild(row);
  wrap.appendChild(children);
  return wrap;
}

function fileNode(entry, depth) {
  const row = document.createElement("div");
  row.className = "node";
  row.style.paddingLeft = rowPad(depth) + 12 + "px";
  row.innerHTML = `<span class="icon">▤</span><span class="label"></span>`;
  row.querySelector(".label").textContent = entry.name;
  row.addEventListener("click", () => openFile(entry.path));
  return row;
}

async function openFile(path) {
  try {
    const res = await fetch(`${KERNEL}/files/read?path=${encodeURIComponent(path)}`);
    if (!res.ok) return;
    const data = await res.json();
    el("previewName").textContent = path + (data.truncated ? "  (truncated)" : "");
    el("previewBody").textContent = data.content;
    el("log").classList.add("hidden");
    preview.classList.remove("hidden");
  } catch (e) {
    /* ignore */
  }
}

el("previewClose").addEventListener("click", () => {
  preview.classList.add("hidden");
  el("log").classList.remove("hidden");
});

el("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  send();
});
input.addEventListener("keydown", (e) => {
  if (handleMenuKey(e)) return;
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});
input.addEventListener("input", () => { autosize(); updateMenu(); });
input.addEventListener("blur", () => setTimeout(hideMenu, 150));


// --- @ file mentions and / slash commands -----------------------------------
let fileList = null; // cached flat workspace file list
let menuMode = null; // "file" | "command" | null
let menuItems = [];
let menuIndex = 0;
const composerMenu = el("composerMenu");

const COMMANDS = [
  { name: "new", desc: "Start a new conversation", run: () => newChat() },
  { name: "clear", desc: "Clear the current view", run: () => clearLog() },
  { name: "files", desc: "Toggle the sidebar", run: () => el("sidebarToggle").click() },
  { name: "model", desc: "Focus the model field", run: () => modelInput.focus() },
  { name: "help", desc: "List commands and @ usage", run: () => showHelp() },
];

function showHelp() {
  appendBot(
    "Commands: " +
      COMMANDS.map((c) => "/" + c.name).join(", ") +
      "\nMention a file with @path to include its contents (e.g. @README.md)."
  );
  scroll();
}

async function ensureFileList() {
  if (fileList) return fileList;
  try {
    fileList = (await (await fetch(`${KERNEL}/files/list`)).json()).files || [];
  } catch (e) {
    fileList = [];
  }
  return fileList;
}

function currentToken() {
  const caret = input.selectionStart;
  const before = input.value.slice(0, caret);
  if (!before) return null;
  if (before[0] === "/" && before.indexOf(" ") === -1) {
    return { mode: "command", query: before.slice(1), start: 0, end: caret };
  }
  const at = before.lastIndexOf("@");
  if (at !== -1 && before.slice(at + 1).indexOf(" ") === -1) {
    return { mode: "file", query: before.slice(at + 1), start: at, end: caret };
  }
  return null;
}

async function updateMenu() {
  const tok = currentToken();
  if (!tok) return hideMenu();
  if (tok.mode === "command") {
    const q = tok.query.toLowerCase();
    menuItems = COMMANDS.filter((c) => c.name.startsWith(q)).map((c) => ({
      label: "/" + c.name,
      hint: c.desc,
      value: c,
    }));
    menuMode = "command";
  } else {
    const files = await ensureFileList();
    const q = tok.query.toLowerCase();
    menuItems = files
      .filter((f) => f.toLowerCase().includes(q))
      .slice(0, 8)
      .map((f) => ({ label: f, hint: "", value: f }));
    menuMode = "file";
  }
  if (!menuItems.length) return hideMenu();
  menuIndex = 0;
  renderMenu(tok);
}

function renderMenu(tok) {
  composerMenu.innerHTML = "";
  menuItems.forEach((it, i) => {
    const row = document.createElement("div");
    row.className = "cmenu-item" + (i === menuIndex ? " active" : "");
    row.innerHTML = `<span class="cmenu-label"></span><span class="cmenu-hint"></span>`;
    row.querySelector(".cmenu-label").textContent = it.label;
    row.querySelector(".cmenu-hint").textContent = it.hint;
    row.addEventListener("mousedown", (e) => {
      e.preventDefault();
      acceptItem(i, tok);
    });
    composerMenu.appendChild(row);
  });
  composerMenu.classList.remove("hidden");
  composerMenu._tok = tok;
}

function hideMenu() {
  menuMode = null;
  menuItems = [];
  composerMenu.classList.add("hidden");
}

function handleMenuKey(e) {
  if (menuMode === null) return false;
  if (e.key === "ArrowDown") {
    menuIndex = (menuIndex + 1) % menuItems.length;
    renderMenu(composerMenu._tok);
    e.preventDefault();
    return true;
  }
  if (e.key === "ArrowUp") {
    menuIndex = (menuIndex - 1 + menuItems.length) % menuItems.length;
    renderMenu(composerMenu._tok);
    e.preventDefault();
    return true;
  }
  if (e.key === "Enter" || e.key === "Tab") {
    acceptItem(menuIndex, composerMenu._tok);
    e.preventDefault();
    return true;
  }
  if (e.key === "Escape") {
    hideMenu();
    e.preventDefault();
    return true;
  }
  return false;
}

function acceptItem(i, tok) {
  const it = menuItems[i];
  if (!it) return;
  if (menuMode === "command") {
    hideMenu();
    input.value = "";
    autosize();
    it.value.run();
    return;
  }
  const v = input.value;
  const before = v.slice(0, tok.start);
  const after = v.slice(tok.end);
  const insert = "@" + it.value + " ";
  input.value = before + insert + after;
  const caret = (before + insert).length;
  hideMenu();
  autosize();
  input.focus();
  input.setSelectionRange(caret, caret);
}

async function expandMentions(text) {
  const mentions = [...new Set((text.match(/@[^ ]+/g) || []).map((m) => m.slice(1)))];
  if (!mentions.length) return text;
  let extra = "";
  for (const path of mentions) {
    try {
      const res = await fetch(`${KERNEL}/files/read?path=${encodeURIComponent(path)}`);
      if (!res.ok) continue;
      const d = await res.json();
      extra += "\n\n@" + path + ":\n```\n" + d.content + "\n```";
    } catch (e) {
      /* ignore */
    }
  }
  return text + extra;
}

boot();
