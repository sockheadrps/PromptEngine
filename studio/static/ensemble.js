const SNAPSHOT_KEY = "pl-registry-snapshots-v1";
const REGISTRY_KEY = "pl-registry-v2";
const CONN_KEY = "promptlibretto.connection.v1";

let activeReader = null;
const participantState = { a: null, b: null };

// ── connection ────────────────────────────────────────────────────

function getStudioConnection() {
  try {
    const raw = localStorage.getItem(CONN_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch (_) { return null; }
}

function renderConnChip() {
  const chip = document.getElementById("conn-chip");
  const conn = getStudioConnection();
  if (!conn || !conn.baseUrl) {
    chip.textContent = "⚠ no studio connection";
    chip.classList.add("missing");
    return;
  }
  let host;
  try { host = new URL(conn.baseUrl).host; } catch { host = conn.baseUrl; }
  const model = conn.model || "no model";
  chip.textContent = `${host} · ${model}`;
  chip.classList.remove("missing");
}

// ── snapshots ─────────────────────────────────────────────────────

function loadSnapshots() {
  const raw = localStorage.getItem(SNAPSHOT_KEY);
  let snaps = [];
  try { snaps = JSON.parse(raw) || []; } catch (_) {}

  // Also offer current studio registry as an option
  const current = localStorage.getItem(REGISTRY_KEY);

  for (const side of ["a", "b"]) {
    const sel = document.getElementById(`${side}-snapshot`);
    sel.innerHTML = '<option value="">— select snapshot —</option>';

    if (current) {
      const opt = document.createElement("option");
      opt.value = "__current__";
      opt.textContent = "current studio registry";
      sel.appendChild(opt);
    }

    for (const snap of snaps) {
      const opt = document.createElement("option");
      opt.value = snap.name;
      opt.textContent = snap.name;
      sel.appendChild(opt);
    }
  }

  return snaps;
}

function snapToHydrateState(snap) {
  return {
    selections:     snap.selections       || {},
    array_modes:    snap.arrayModes       || {},
    section_random: snap.sectionRandom    || {},
    sliders:        snap.sectionSliders   || {},
    slider_random:  snap.sectionSliderRandom || {},
    template_vars:  snap.tvarValues       || {},
  };
}

function loadSnapshot(side) {
  const sel = document.getElementById(`${side}-snapshot`);
  const val = sel.value;
  if (!val) return;

  let registry = null;
  let snap = null;

  if (val === "__current__") {
    const raw = localStorage.getItem(REGISTRY_KEY);
    try { registry = JSON.parse(raw); } catch (_) {}
  } else {
    const raw = localStorage.getItem(SNAPSHOT_KEY);
    let snaps = [];
    try { snaps = JSON.parse(raw) || []; } catch (_) {}
    snap = snaps.find(s => s.name === val) || null;
    if (snap) registry = snap.registry ?? snap.data ?? snap;
  }

  if (!registry) {
    setStatus("snapshot not found or empty");
    return;
  }

  document.getElementById(`${side}-registry`).value = JSON.stringify(registry, null, 2);

  // store hydrate state extracted from the snapshot
  participantState[side] = snap ? snapToHydrateState(snap) : null;

  // prefer model from registry generation config, fall back to studio connection model
  const reg = registry?.registry ?? registry;
  const model = reg?.generation?.model || getStudioConnection()?.model;
  if (model) document.getElementById(`${side}-model`).value = model;
}

// ── run ───────────────────────────────────────────────────────────

function parseRegistry(side) {
  const raw = document.getElementById(`${side}-registry`).value.trim();
  if (!raw) throw new Error(`Participant ${side.toUpperCase()}: registry JSON is empty`);
  try {
    return JSON.parse(raw);
  } catch (e) {
    throw new Error(`Participant ${side.toUpperCase()}: invalid JSON — ${e.message}`);
  }
}

function setStatus(msg) {
  document.getElementById("status").textContent = msg;
}

function setRunning(running) {
  document.getElementById("btn-run").disabled = running;
  document.getElementById("btn-stop").classList.toggle("visible", running);
}

async function startEnsemble() {
  let registryA, registryB;
  try {
    registryA = parseRegistry("a");
    registryB = parseRegistry("b");
  } catch (e) {
    setStatus(e.message);
    return;
  }

  const seed = document.getElementById("seed").value.trim();
  if (!seed) { setStatus("seed message is required"); return; }

  const conn = getStudioConnection();
  if (!conn || !conn.baseUrl) {
    setStatus("no studio connection — configure it in Studio first");
    return;
  }

  const turns = parseInt(document.getElementById("turns").value, 10) || 8;
  const nameA = document.getElementById("a-name").value.trim() || "A";
  const nameB = document.getElementById("b-name").value.trim() || "B";
  const modelA = document.getElementById("a-model").value.trim() || conn.model || "llama3";
  const modelB = document.getElementById("b-model").value.trim() || conn.model || "llama3";

  clearConversation();
  showSeed(seed);
  setRunning(true);
  setStatus("connecting…");

  const body = JSON.stringify({
    a: { registry: registryA, model: modelA, name: nameA, state: participantState.a || {} },
    b: { registry: registryB, model: modelB, name: nameB, state: participantState.b || {} },
    seed,
    turns,
    connection: {
      base_url: conn.baseUrl,
      chat_path: conn.chatPath || "/api/chat",
      payload_shape: conn.payloadShape || "auto",
    },
  });

  try {
    const resp = await fetch("/api/ensemble/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });

    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`server error ${resp.status}: ${text}`);
    }

    const reader = resp.body.getReader();
    activeReader = reader;
    const decoder = new TextDecoder();
    let buf = "";

    setStatus("running…");

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith("data:")) continue;
        const payload = line.slice(5).trim();
        if (!payload) continue;
        let event;
        try { event = JSON.parse(payload); } catch (_) { continue; }
        handleEvent(event, nameA, nameB);
      }
    }
  } catch (e) {
    if (e.name !== "AbortError") {
      showError(e.message);
      setStatus("error");
    }
  } finally {
    activeReader = null;
    setRunning(false);
  }
}

function stopEnsemble() {
  if (activeReader) {
    activeReader.cancel();
    activeReader = null;
  }
  setRunning(false);
  setStatus("stopped");
}

// ── event handling ────────────────────────────────────────────────

let currentBubble = null;
let turnCount = 0;

function handleEvent(event, nameA, nameB) {
  if (event.type === "turn_start") {
    const side = event.speaker === nameA ? "a" : "b";
    currentBubble = createTurnBubble(side, event.speaker, event.turn + 1);
    scrollToBottom();
  } else if (event.type === "chunk") {
    if (currentBubble) appendChunk(currentBubble, event.text);
    scrollToBottom();
  } else if (event.type === "turn_end") {
    if (currentBubble) finalizeBubble(currentBubble);
    currentBubble = null;
    turnCount++;
    setStatus(`turn ${turnCount} / ${document.getElementById("turns").value}`);
  } else if (event.type === "done") {
    showDone();
    setStatus(`done — ${turnCount} turns`);
    setRunning(false);
  } else if (event.type === "error") {
    showError(event.message);
    setStatus("error");
    setRunning(false);
  }
}

// ── conversation DOM ──────────────────────────────────────────────

function clearConversation() {
  const el = document.getElementById("conversation");
  el.innerHTML = "";
  currentBubble = null;
  turnCount = 0;
}

function showSeed(text) {
  const el = document.getElementById("conversation");
  const div = document.createElement("div");
  div.className = "seed-display";
  div.innerHTML = `<div class="seed-label">seed</div>${escHtml(text)}`;
  el.appendChild(div);
}

function createTurnBubble(side, name, num) {
  const conv = document.getElementById("conversation");
  const turn = document.createElement("div");
  turn.className = `turn speaker-${side}`;

  const label = document.createElement("div");
  label.className = "turn-label";
  label.textContent = `${name}  ·  turn ${num}`;

  const bubble = document.createElement("div");
  bubble.className = "turn-bubble";

  const cursor = document.createElement("span");
  cursor.className = "turn-cursor";
  bubble.appendChild(cursor);

  turn.appendChild(label);
  turn.appendChild(bubble);
  conv.appendChild(turn);

  return { bubble, cursor };
}

function appendChunk({ bubble, cursor }, text) {
  const node = document.createTextNode(text);
  bubble.insertBefore(node, cursor);
}

function finalizeBubble({ bubble, cursor }) {
  cursor.remove();
}

function showDone() {
  const conv = document.getElementById("conversation");
  const div = document.createElement("div");
  div.className = "done-marker";
  div.textContent = "— conversation complete —";
  conv.appendChild(div);
  scrollToBottom();
}

function showError(msg) {
  const conv = document.getElementById("conversation");
  const div = document.createElement("div");
  div.className = "error-marker";
  div.textContent = `error: ${msg}`;
  conv.appendChild(div);
  scrollToBottom();
}

function scrollToBottom() {
  const conv = document.getElementById("conversation");
  conv.scrollTop = conv.scrollHeight;
}

function escHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// ── init ──────────────────────────────────────────────────────────

window.addEventListener("load", () => {
  loadSnapshots();
  renderConnChip();

  // pre-fill model fields from studio connection
  const conn = getStudioConnection();
  if (conn?.model) {
    document.getElementById("a-model").value = conn.model;
    document.getElementById("b-model").value = conn.model;
  }
});

window.addEventListener("focus", () => {
  loadSnapshots();
  renderConnChip();
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    loadSnapshots();
    renderConnChip();
  }
});

window.addEventListener("storage", (e) => {
  if (e.key === SNAPSHOT_KEY || e.key === REGISTRY_KEY) loadSnapshots();
  if (e.key === CONN_KEY) renderConnChip();
});
