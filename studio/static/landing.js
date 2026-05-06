import { getWorkspaceId, setWorkspaceId } from "/static/session.js";
import { listModels } from "/static/ollama_client.js";

// ── Tab switching ────────────────────────────────────────────
document.querySelectorAll('.conn-tab').forEach(btn => {
  btn.addEventListener('click', () => {
    const tab = btn.dataset.tab;
    document.querySelectorAll('.conn-tab').forEach(b => b.classList.toggle('active', b === btn));
    document.querySelectorAll('.conn-tab-panel').forEach(p => { p.hidden = p.id !== 'conn-tab-' + tab; });
  });
});

// ── About modal open/close ───────────────────────────────────
const aboutModal = document.getElementById('about-modal');
document.getElementById('about-open-btn').addEventListener('click', () => { aboutModal.hidden = false; });
document.getElementById('about-close-btn').addEventListener('click', () => { aboutModal.hidden = true; });
aboutModal.addEventListener('click', e => { if (e.target === aboutModal) aboutModal.hidden = true; });
document.addEventListener('keydown', e => { if (e.key === 'Escape') aboutModal.hidden = true; });

// ── CORS origin labels ───────────────────────────────────────
const origin = window.location.origin;
document.querySelectorAll("#cors-origin-win, #cors-origin-nix").forEach(el => el.textContent = origin);

window.switchCorsTab = function(which) {
  document.getElementById("cors-tab-win").hidden = which !== "win";
  document.getElementById("cors-tab-nix").hidden = which !== "nix";
  document.getElementById("cors-btn-win").classList.toggle("cors-tab-active", which === "win");
  document.getElementById("cors-btn-nix").classList.toggle("cors-tab-active", which === "nix");
};

// ── Workspace identity ───────────────────────────────────────
const wsDisplay = document.getElementById("ws-uuid-display");
const wsStatus  = document.getElementById("ws-status");

function refreshUuid() {
  wsDisplay.textContent = getWorkspaceId();
}
refreshUuid();

document.getElementById("ws-copy-btn").addEventListener("click", async () => {
  await navigator.clipboard.writeText(getWorkspaceId());
  wsStatus.textContent = "Copied.";
  wsStatus.dataset.kind = "ok";
  setTimeout(() => { wsStatus.textContent = ""; wsStatus.dataset.kind = ""; }, 2000);
});

document.getElementById("ws-apply-btn").addEventListener("click", () => {
  const v = document.getElementById("ws-restore-input").value.trim();
  const isUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);
  if (!isUuid) {
    wsStatus.textContent = "That doesn't look like a UUID.";
    wsStatus.dataset.kind = "err";
    return;
  }
  setWorkspaceId(v);
  window.location.reload();
});

// ── Connection form (Chat model) ─────────────────────────────
const STORAGE_KEY = "promptlibretto.connection.v1";
const EMBED_KEY   = "promptlibretto.embed.v1";
const CLASS_KEY   = "promptlibretto.classifier.v1";

function loadJson(key) {
  try { const r = localStorage.getItem(key); if (r) return JSON.parse(r); } catch {}
  return {};
}
function saveJson(key, obj) {
  try { localStorage.setItem(key, JSON.stringify(obj)); } catch {}
}

const elUrl    = document.getElementById("conn-base-url");
const elPath   = document.getElementById("conn-chat-path");
const elShape  = document.getElementById("conn-shape");
const elModel  = document.getElementById("conn-model");
const elStatus = document.getElementById("conn-status");

const stored = loadJson(STORAGE_KEY);
elUrl.value   = stored.baseUrl   || "http://localhost:11434";
elPath.value  = stored.chatPath  || "/api/chat";
elShape.value = stored.payloadShape || "auto";

function setStatus(el, msg, kind) {
  el.textContent = msg;
  el.dataset.kind = kind || "";
}

function populateModels(names, selected) {
  elModel.innerHTML = "";
  if (!names.length) {
    const opt = document.createElement("option");
    opt.value = ""; opt.textContent = "— no models yet —";
    elModel.appendChild(opt);
    return;
  }
  for (const n of names) {
    const opt = document.createElement("option");
    opt.value = n; opt.textContent = n;
    if (n === selected) opt.selected = true;
    elModel.appendChild(opt);
  }
}

if (stored.model) populateModels([stored.model], stored.model);
else populateModels([], "");

let testSeq = 0;
async function doTest(manual = true) {
  const baseUrl = elUrl.value.trim() || "http://localhost:11434";
  const chatPath = elPath.value.trim() || "/api/chat";
  const payloadShape = elShape.value || "auto";
  if (!/^https?:\/\//.test(baseUrl)) {
    if (manual) setStatus(elStatus, "Enter a full URL (http://host:port).", "warn");
    return;
  }
  const seq = ++testSeq;
  setStatus(elStatus, "Checking…", "");
  try {
    const models = await listModels({ baseUrl, chatPath, payloadShape });
    if (seq !== testSeq) return;
    if (!models.length) {
      setStatus(elStatus, "Reached the server but no models listed.", "warn");
      populateModels([], "");
      updateSidebarConn("no models", "warn");
      return;
    }
    populateModels(models, stored.model || models[0]);
    setStatus(elStatus, `${models.length} model${models.length === 1 ? "" : "s"} available.`, "ok");
    updateSidebarConn(elModel.value || models[0], "ok");
  } catch (err) {
    if (seq !== testSeq) return;
    setStatus(elStatus, `Can't reach server: ${err.message || err}`, manual ? "err" : "warn");
    populateModels([], "");
    updateSidebarConn("unreachable", manual ? "err" : "");
  }
}

function updateSidebarConn(msg, kind) {
  const el = document.getElementById("sidebar-conn-status");
  if (el) { el.textContent = msg; el.dataset.kind = kind || ""; }
}
function updateSidebarEmbed(msg, kind) {
  const el = document.getElementById("sidebar-embed-status");
  if (el) { el.textContent = msg; el.dataset.kind = kind || ""; }
}
function updateSidebarClassifier(msg, kind) {
  const el = document.getElementById("sidebar-classifier-status");
  if (el) { el.textContent = msg; el.dataset.kind = kind || ""; }
}

document.getElementById("conn-test-btn").addEventListener("click", () => doTest(true));

let debounce;
[elUrl, elPath].forEach(el => el.addEventListener("input", () => {
  clearTimeout(debounce);
  debounce = setTimeout(() => doTest(false), 400);
}));
elShape.addEventListener("change", () => doTest(false));

document.getElementById("conn-save-btn").addEventListener("click", () => {
  const model = elModel.value;
  if (!model) { setStatus(elStatus, "Pick a model before saving.", "err"); return; }
  saveJson(STORAGE_KEY, {
    baseUrl: elUrl.value.trim() || "http://localhost:11434",
    chatPath: elPath.value.trim() || "/api/chat",
    payloadShape: elShape.value || "auto",
    model,
  });
  setStatus(elStatus, "Saved.", "ok");
  setTimeout(() => { elStatus.textContent = ""; elStatus.dataset.kind = ""; }, 2000);
});

if (stored.baseUrl) doTest(false);

// ── Embed model ──────────────────────────────────────────────
const embedStored = loadJson(EMBED_KEY);
const elEmbedUrl   = document.getElementById("embed-base-url");
const elEmbedModel = document.getElementById("embed-model");
const elEmbedSt    = document.getElementById("embed-status");

elEmbedUrl.value = embedStored.baseUrl || "";

function populateEmbedModels(names, selected) {
  elEmbedModel.innerHTML = "";
  if (!names.length) {
    const opt = document.createElement("option");
    opt.value = ""; opt.textContent = "— enter a valid base URL —";
    elEmbedModel.appendChild(opt);
    return;
  }
  for (const n of names) {
    const opt = document.createElement("option");
    opt.value = n; opt.textContent = n;
    if (n === selected) opt.selected = true;
    elEmbedModel.appendChild(opt);
  }
}
populateEmbedModels([], "");

let embedUrlSeq = 0;
async function fetchEmbedModels(manual = false) {
  const baseUrl = elEmbedUrl.value.trim();
  if (!baseUrl) return;
  if (!/^https?:\/\/.+/.test(baseUrl)) {
    setStatus(elEmbedSt, "Enter a full URL (http://host:port).", "warn");
    return;
  }
  const seq = ++embedUrlSeq;
  setStatus(elEmbedSt, "Fetching models…", "");
  try {
    const models = await listModels({ baseUrl, chatPath: "/api/chat", payloadShape: "auto" });
    if (seq !== embedUrlSeq) return;
    if (!models.length) {
      setStatus(elEmbedSt, "Reached server but no models listed.", "warn");
      populateEmbedModels([], "");
      return;
    }
    populateEmbedModels(models, embedStored.model || models[0]);
    setStatus(elEmbedSt, `${models.length} model${models.length === 1 ? "" : "s"} available.`, "ok");
  } catch (err) {
    if (seq !== embedUrlSeq) return;
    setStatus(elEmbedSt, `Can't reach server: ${err.message || err}`, manual ? "err" : "warn");
    populateEmbedModels([], "");
  }
}

elEmbedUrl.addEventListener("blur", () => fetchEmbedModels(true));
let embedDebounce;
elEmbedUrl.addEventListener("input", () => {
  clearTimeout(embedDebounce);
  embedDebounce = setTimeout(() => fetchEmbedModels(false), 500);
});

async function testEmbed() {
  const baseUrl = elEmbedUrl.value.trim();
  const model   = elEmbedModel.value;
  if (!baseUrl || !model) {
    setStatus(elEmbedSt, "Enter a base URL and select a model.", "err");
    return;
  }
  setStatus(elEmbedSt, "Testing…", "");
  try {
    const resp = await fetch("/api/test-embed", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ baseUrl, model }),
    });
    const data = resp.ok ? await resp.json() : null;
    if (resp.ok && data && data.ok) {
      setStatus(elEmbedSt, data.message || "Connection OK.", "ok");
      updateSidebarEmbed(model, "ok");
    } else {
      setStatus(elEmbedSt, `Server responded ${resp.status}. Check URL and model.`, "err");
      updateSidebarEmbed("error", "err");
    }
  } catch (err) {
    setStatus(elEmbedSt, `Could not reach ${baseUrl}: ${err.message || err}`, "err");
    updateSidebarEmbed("unreachable", "err");
  }
}

document.getElementById("embed-test-btn").addEventListener("click", testEmbed);
document.getElementById("embed-save-btn").addEventListener("click", () => {
  saveJson(EMBED_KEY, {
    baseUrl: elEmbedUrl.value.trim(),
    model: elEmbedModel.value,
  });
  setStatus(elEmbedSt, "Saved.", "ok");
  setTimeout(() => { elEmbedSt.textContent = ""; elEmbedSt.dataset.kind = ""; }, 2000);
});

if (embedStored.baseUrl) fetchEmbedModels(false);
if (embedStored.baseUrl && embedStored.model) {
  fetch("/api/test-embed", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ baseUrl: embedStored.baseUrl, model: embedStored.model }),
  }).then(r => r.ok ? r.json() : null).then(data => {
    if (data && data.ok) {
      updateSidebarEmbed(embedStored.model, "ok");
      setStatus(elEmbedSt, data.message || "Connection OK.", "ok");
    } else {
      updateSidebarEmbed(embedStored.model, "");
    }
  }).catch(() => { updateSidebarEmbed(embedStored.model, ""); });
}

// ── Classifier model ─────────────────────────────────────────
const classStored = loadJson(CLASS_KEY);
const elClassUrl   = document.getElementById("classifier-base-url");
const elClassModel = document.getElementById("classifier-model");
const elClassSt    = document.getElementById("classifier-status");

elClassUrl.value = classStored.baseUrl || "";

function populateClassifierModels(names, selected) {
  elClassModel.innerHTML = "";
  if (!names.length) {
    const opt = document.createElement("option");
    opt.value = ""; opt.textContent = "— enter a valid base URL —";
    elClassModel.appendChild(opt);
    return;
  }
  for (const n of names) {
    const opt = document.createElement("option");
    opt.value = n; opt.textContent = n;
    if (n === selected) opt.selected = true;
    elClassModel.appendChild(opt);
  }
}
populateClassifierModels([], "");

let classUrlSeq = 0;
async function fetchClassifierModels(manual = false) {
  const baseUrl = elClassUrl.value.trim();
  if (!baseUrl) return;
  if (!/^https?:\/\/.+/.test(baseUrl)) {
    setStatus(elClassSt, "Enter a full URL (http://host:port).", "warn");
    return;
  }
  const seq = ++classUrlSeq;
  setStatus(elClassSt, "Fetching models…", "");
  try {
    const models = await listModels({ baseUrl, chatPath: "/api/chat", payloadShape: "auto" });
    if (seq !== classUrlSeq) return;
    if (!models.length) {
      setStatus(elClassSt, "Reached server but no models listed.", "warn");
      populateClassifierModels([], "");
      return;
    }
    populateClassifierModels(models, classStored.model || models[0]);
    setStatus(elClassSt, `${models.length} model${models.length === 1 ? "" : "s"} available.`, "ok");
  } catch (err) {
    if (seq !== classUrlSeq) return;
    setStatus(elClassSt, `Can't reach server: ${err.message || err}`, manual ? "err" : "warn");
    populateClassifierModels([], "");
  }
}

elClassUrl.addEventListener("blur", () => fetchClassifierModels(true));
let classDebounce;
elClassUrl.addEventListener("input", () => {
  clearTimeout(classDebounce);
  classDebounce = setTimeout(() => fetchClassifierModels(false), 500);
});

async function testClassifier() {
  const baseUrl = elClassUrl.value.trim();
  const model   = elClassModel.value;
  if (!baseUrl || !model) {
    setStatus(elClassSt, "Enter a base URL and select a model.", "err");
    return;
  }
  setStatus(elClassSt, "Testing…", "");
  try {
    const resp = await fetch("/api/test-classifier", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ baseUrl, model }),
    });
    const data = resp.ok ? await resp.json() : null;
    if (resp.ok && data && data.ok) {
      setStatus(elClassSt, data.message || "Connection OK.", "ok");
      updateSidebarClassifier(model, "ok");
    } else {
      setStatus(elClassSt, `Server responded ${resp.status}. Check URL and model.`, "err");
      updateSidebarClassifier("error", "err");
    }
  } catch (err) {
    setStatus(elClassSt, `Could not reach ${baseUrl}: ${err.message || err}`, "err");
    updateSidebarClassifier("unreachable", "err");
  }
}

document.getElementById("classifier-test-btn").addEventListener("click", testClassifier);
document.getElementById("classifier-save-btn").addEventListener("click", () => {
  saveJson(CLASS_KEY, {
    baseUrl: elClassUrl.value.trim(),
    model: elClassModel.value,
  });
  setStatus(elClassSt, "Saved.", "ok");
  setTimeout(() => { elClassSt.textContent = ""; elClassSt.dataset.kind = ""; }, 2000);
});

if (classStored.baseUrl) fetchClassifierModels(false);
if (classStored.baseUrl && classStored.model) {
  fetch("/api/test-classifier", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ baseUrl: classStored.baseUrl, model: classStored.model }),
  }).then(r => r.ok ? r.json() : null).then(data => {
    if (data && data.ok) {
      updateSidebarClassifier(classStored.model, "ok");
      setStatus(elClassSt, data.message || "Connection OK.", "ok");
    } else {
      updateSidebarClassifier(classStored.model, "");
    }
  }).catch(() => { updateSidebarClassifier(classStored.model, ""); });
}

// ── About slideshow ──────────────────────────────────────────
const slides = Array.from(document.querySelectorAll(".about-slide"));
const dotsEl = document.getElementById("about-dots");
const prevBtn = document.getElementById("about-prev");
const nextBtn = document.getElementById("about-next");
let currentSlide = 0;

slides.forEach((_, i) => {
  const dot = document.createElement("div");
  dot.className = "about-dot" + (i === 0 ? " active" : "");
  dot.addEventListener("click", () => goTo(i));
  dotsEl.appendChild(dot);
});

function goTo(idx) {
  slides[currentSlide].classList.remove("active");
  dotsEl.children[currentSlide].classList.remove("active");
  currentSlide = Math.max(0, Math.min(idx, slides.length - 1));
  slides[currentSlide].classList.add("active");
  dotsEl.children[currentSlide].classList.add("active");
  prevBtn.disabled = currentSlide === 0;
  nextBtn.disabled = currentSlide === slides.length - 1;
  const step = currentSlide + 1;
  document.querySelectorAll("#about-diagram [data-step]").forEach(el => {
    const elStep = parseInt(el.dataset.step, 10);
    el.style.opacity = elStep <= step ? "1" : "0.25";
  });
}

prevBtn.addEventListener("click", () => goTo(currentSlide - 1));
nextBtn.addEventListener("click", () => goTo(currentSlide + 1));
goTo(0);
