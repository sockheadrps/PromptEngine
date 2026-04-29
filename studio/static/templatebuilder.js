const SECTION_KEYS = [
  "base_context",
  "personas",
  "sentiment",
  "static_injections",
  "runtime_injections",
  "output_prompt_directions",
  "examples",
  "prompt_endings",
];

const SECTION_LABELS = {
  base_context: "Base Context",
  personas: "Personas",
  sentiment: "Sentiment Contexts",
  static_injections: "Static Injections",
  runtime_injections: "Runtime Injections",
  output_prompt_directions: "Output Directions",
  examples: "Examples",
  prompt_endings: "Prompt Endings",
};

const STUDIO_INBOX_KEY = "pl-studio-handoff-v1";
const BUILDER_INBOX_KEY = "pl-builder-handoff-v1";
const GEN_FIELDS = [
  ["temperature", "gen-temperature", parseFloat],
  ["top_p", "gen-top-p", parseFloat],
  ["top_k", "gen-top-k", parseInt],
  ["max_tokens", "gen-max-tokens", parseInt],
  ["repeat_penalty", "gen-repeat-penalty", parseFloat],
  ["retries", "gen-retries", parseInt],
  ["max_prompt_chars", "gen-max-prompt-chars", parseInt],
];
const POLICY_LIST_FIELDS = [
  ["strip_prefixes", "policy-strip-prefixes"],
  ["strip_patterns", "policy-strip-patterns"],
  ["require_patterns", "policy-required-patterns"],
  ["forbidden_substrings", "policy-forbidden-substrings"],
  ["forbidden_patterns", "policy-forbidden-patterns"],
];
const DEFAULT_ASSEMBLY_ORDER = [
  "output_prompt_directions",
  "sentiment.context",
  "persona.text",
  "persona.base_directives",
  "sentiment.nudges",
  "injections",
  "examples.normal_examples",
  "examples[sentiment.example_pool]",
  "examples.prompt_endings",
];

let registryState = createEmptyRegistryState();
let currentModalContext = null;
let activeBuilderTab = "sections";

const ASSEMBLY_STEP_OPTIONS = [
  {
    key: "output_prompt_directions",
    label: "Output Directions",
    detail: "Add output formatting rules and final answer constraints.",
    variants: [{ token: "output_prompt_directions", label: "All output directions" }],
  },
  {
    key: "base_context",
    label: "Base Context",
    detail: "Add the general framing for the task or scene.",
    variants: [
      { token: "base_context", label: "All base context" },
      { token: "base_context.text", label: "Primary base-context text" },
    ],
  },
  {
    key: "persona",
    label: "Persona",
    detail: "Insert persona identity or persona directives.",
    variants: [
      { token: "persona.context", label: "Persona context" },
      { token: "persona.text", label: "Persona context (legacy token)" },
      { token: "persona.base_directives", label: "Persona directives" },
    ],
  },
  {
    key: "sentiment",
    label: "Sentiment",
    detail: "Layer in tone framing, nudges, or sentiment examples.",
    variants: [
      { token: "sentiment.context", label: "Sentiment context" },
      { token: "sentiment.nudges", label: "Sentiment nudges" },
      { token: "sentiment.examples", label: "Sentiment examples" },
      { token: "sentiment.scale", label: "Sentiment scale" },
    ],
  },
  {
    key: "injections",
    label: "Injections",
    detail: "Apply static or runtime injection content.",
    variants: [
      { token: "injections", label: "All static injections" },
      { token: "runtime_injections", label: "Runtime injections" },
    ],
  },
  {
    key: "examples",
    label: "Examples",
    detail: "Use a named examples pool or a runtime-selected pool.",
    variants: [],
  },
  {
    key: "prompt_endings",
    label: "Prompt Endings",
    detail: "Finish with one or more prompt ending cues.",
    variants: [{ token: "prompt_endings", label: "All prompt endings" }],
  },
];

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));
}

function createEmptyRegistryState() {
  const state = {
    version: 22,
    title: "Twitch Chatter",
    description: "v2.2 Declarative Model",
    assembly_order: [],
    generation: {},
    generationExtras: {},
    output_policy: {},
    outputPolicyExtras: {},
    extraTopLevel: {},
    sections: {},
  };

  SECTION_KEYS.forEach((key) => {
    state.sections[key] = {
      required: key !== "static_injections" && key !== "runtime_injections" && key !== "examples",
      template_vars: [],
      items: [],
      extras: {},
    };
  });

  return state;
}

function safeParseJson(label, text) {
  const raw = String(text || "").trim();
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error(`${label} must be a JSON object.`);
    }
    return parsed;
  } catch (err) {
    throw new Error(`${label}: ${err.message}`);
  }
}

function setValidationStatus(message, ok = false) {
  const el = document.getElementById("validation-status");
  if (!el) return;
  el.textContent = message;
  el.classList.toggle("ok", !!ok);
  el.classList.toggle("error", !ok);
}

function readListField(id) {
  const el = document.getElementById(id);
  if (!el) return [];
  return String(el.value || "")
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}

function readGenerationFields() {
  const out = { ...registryState.generationExtras };
  for (const [key, id, parse] of GEN_FIELDS) {
    const el = document.getElementById(id);
    if (!el || el.value === "" || el.value == null) continue;
    const n = parse(el.value, 10);
    if (Number.isFinite(n)) out[key] = n;
  }
  return out;
}

function readPolicyFields() {
  const out = { ...registryState.outputPolicyExtras };
  const minLength = document.getElementById("policy-min-length")?.value;
  const maxLength = document.getElementById("policy-max-length")?.value;
  const appendSuffix = document.getElementById("policy-append-suffix")?.value || "";
  const collapseWhitespace = !!document.getElementById("policy-collapse-whitespace")?.checked;

  if (minLength !== "") out.min_length = parseInt(minLength, 10);
  if (maxLength !== "") out.max_length = parseInt(maxLength, 10);
  if (collapseWhitespace) out.collapse_whitespace = true;
  else delete out.collapse_whitespace;
  if (appendSuffix.trim()) out.append_suffix = appendSuffix;

  for (const [key, id] of POLICY_LIST_FIELDS) {
    const vals = readListField(id);
    if (vals.length) out[key] = vals;
    else delete out[key];
  }
  return out;
}

function syncTopLevelStateFromInputs() {
  registryState.version = parseInt(document.getElementById("model-version").value, 10) || 0;
  registryState.title = document.getElementById("model-title-input").value;
  registryState.description = document.getElementById("model-desc-input").value;
  document.getElementById("assembly-order-input").value = registryState.assembly_order.join(", ");
  registryState.generation = readGenerationFields();
  registryState.output_policy = readPolicyFields();
}

function buildExportPayload() {
  syncTopLevelStateFromInputs();

  const registry = {
    version: registryState.version,
    title: registryState.title,
    description: registryState.description,
    assembly_order: [...registryState.assembly_order],
    ...registryState.extraTopLevel,
  };

  if (Object.keys(registryState.generation).length) {
    registry.generation = JSON.parse(JSON.stringify(registryState.generation));
  }
  if (Object.keys(registryState.output_policy).length) {
    registry.output_policy = JSON.parse(JSON.stringify(registryState.output_policy));
  }

  SECTION_KEYS.forEach((key) => {
    const sectionData = registryState.sections[key];
    const items = sectionData.items.map(({ _ui_id, ...rest }) => {
      const out = { ...rest };
      if (key === "personas" && out.text) {
        out.context = out.text;
        delete out.text;
      }
      return out;
    });

    registry[key] = {
      required: sectionData.required,
      template_vars: [...sectionData.template_vars],
      items,
      ...sectionData.extras,
    };
  });

  return { registry };
}

function exportFullModel() {
  try {
    const output = buildExportPayload();
    document.getElementById("output-json").textContent = JSON.stringify(output, null, 2);
    setValidationStatus("Ready to validate or open in Studio.");
    return output;
  } catch (err) {
    document.getElementById("output-json").textContent = `ERROR: ${err.message}`;
    setValidationStatus(err.message, false);
    return null;
  }
}

function toggleSection(el) {
  el.classList.toggle("collapsed");
}

function toggleBuilderCollapse(btn) {
  const panel = btn.closest("[data-builder-collapse]");
  if (!panel) return;
  panel.classList.toggle("collapsed");
  btn.textContent = panel.classList.contains("collapsed") ? "Expand" : "Collapse";
}

function switchBuilderTab(tab) {
  activeBuilderTab = tab === "finalize" ? "finalize" : "sections";
  const sectionsTab = document.getElementById("tab-sections");
  const finalizeTab = document.getElementById("tab-finalize");
  const sectionsPanel = document.getElementById("builder-tab-sections-panel");
  const finalizePanel = document.getElementById("builder-tab-finalize-panel");
  if (!sectionsTab || !finalizeTab || !sectionsPanel || !finalizePanel) return;

  const onSections = activeBuilderTab === "sections";
  sectionsTab.classList.toggle("active", onSections);
  finalizeTab.classList.toggle("active", !onSections);
  sectionsTab.setAttribute("aria-selected", onSections ? "true" : "false");
  finalizeTab.setAttribute("aria-selected", onSections ? "false" : "true");
  sectionsPanel.classList.toggle("active", onSections);
  finalizePanel.classList.toggle("active", !onSections);
}

function assemblyGroups() {
  const dynamicItems = (secKey, alias = secKey) =>
    (registryState.sections[secKey]?.items || [])
      .map((item) => item.name || item.id)
      .filter(Boolean)
      .map((name) => ({ token: `${alias}.${name}`, label: `${alias}.${name}` }));

  return [
    {
      title: "Common",
      items: [
        { token: "base_context", label: "base_context" },
        { token: "output_prompt_directions", label: "output_prompt_directions" },
        { token: "persona", label: "persona" },
        { token: "persona.base_directives", label: "persona.base_directives" },
        { token: "sentiment.context", label: "sentiment.context" },
        { token: "sentiment.nudges", label: "sentiment.nudges" },
        { token: "sentiment.examples", label: "sentiment.examples" },
        { token: "sentiment.scale", label: "sentiment.scale" },
        { token: "injections", label: "injections" },
        { token: "runtime_injections", label: "runtime_injections" },
        { token: "prompt_endings", label: "prompt_endings" },
      ],
    },
    {
      title: "Named Pools",
      items: [
        ...dynamicItems("examples"),
        ...dynamicItems("prompt_endings"),
        ...dynamicItems("static_injections", "injections"),
        ...dynamicItems("output_prompt_directions"),
      ],
    },
    {
      title: "Dynamic Expressions",
      items: [
        { token: "examples[sentiment.example_pool]", label: "examples[sentiment.example_pool]" },
      ],
    },
  ].filter((g) => g.items.length);
}

function renderAssemblyOrderEditor() {
  const host = document.getElementById("assembly-order-list");
  const palette = document.getElementById("assembly-token-groups");
  const hidden = document.getElementById("assembly-order-input");
  if (!host || !palette || !hidden) return;

  hidden.value = registryState.assembly_order.join(", ");
  if (!registryState.assembly_order.length) {
    host.innerHTML = `<div class="assembly-order-empty">No tokens yet. Pick from the token picker below.</div>`;
  } else {
    host.innerHTML = registryState.assembly_order
      .map(
        (token, i) =>
          `<div class="assembly-token-chip">` +
          `<span>${escapeHtml(token)}</span>` +
          `<span class="assembly-chip-controls">` +
          `<button type="button" class="assembly-chip-btn" onclick="moveAssemblyToken(${i}, -1)" title="Move left">←</button>` +
          `<button type="button" class="assembly-chip-btn" onclick="moveAssemblyToken(${i}, 1)" title="Move right">→</button>` +
          `<button type="button" class="assembly-chip-btn" onclick="removeAssemblyToken(${i})" title="Remove">×</button>` +
          `</span></div>`
      )
      .join("");
  }

  palette.innerHTML = assemblyGroups()
    .map(
      (group) =>
        `<div class="assembly-group">` +
        `<div class="assembly-group-title">${escapeHtml(group.title)}</div>` +
        `<div class="assembly-group-items">` +
        group.items
          .map(
            (item) =>
              `<button type="button" class="assembly-palette-btn" onclick="addAssemblyToken('${escapeHtml(item.token)}')">${escapeHtml(item.label)}</button>`
          )
          .join("") +
        `</div></div>`
    )
    .join("");
}

function addAssemblyToken(token) {
  if (!token) return;
  registryState.assembly_order.push(token);
  renderAssemblyOrderEditor();
  exportFullModel();
}

function addCustomAssemblyToken() {
  const el = document.getElementById("assembly-custom-token");
  if (!el) return;
  const token = el.value.trim();
  if (!token) return;
  registryState.assembly_order.push(token);
  el.value = "";
  renderAssemblyOrderEditor();
  exportFullModel();
}

function removeAssemblyToken(index) {
  registryState.assembly_order.splice(index, 1);
  renderAssemblyOrderEditor();
  exportFullModel();
}

function moveAssemblyToken(index, delta) {
  const next = index + delta;
  if (next < 0 || next >= registryState.assembly_order.length) return;
  const arr = registryState.assembly_order;
  [arr[index], arr[next]] = [arr[next], arr[index]];
  renderAssemblyOrderEditor();
  exportFullModel();
}

function dynamicAssemblyVariants() {
  const namedItems = (secKey, alias = secKey, prefix = SECTION_LABELS[secKey]) =>
    (registryState.sections[secKey]?.items || [])
      .map((item) => item.name || item.id)
      .filter(Boolean)
      .map((name) => ({
        token: `${alias}.${name}`,
        label: `${prefix}: ${name}`,
      }));

  return {
    examples: [
      ...namedItems("examples", "examples", "Examples"),
      { token: "examples[sentiment.example_pool]", label: "Examples: pool from sentiment.example_pool" },
    ],
    prompt_endings: namedItems("prompt_endings", "prompt_endings", "Prompt Ending"),
    injections: namedItems("static_injections", "injections", "Static Injection"),
    output_prompt_directions: namedItems("output_prompt_directions", "output_prompt_directions", "Output Direction"),
  };
}

function assemblyStepOptions() {
  const dynamic = dynamicAssemblyVariants();
  return ASSEMBLY_STEP_OPTIONS.map((option) => {
    if (option.key === "examples") return { ...option, variants: dynamic.examples };
    if (option.key === "prompt_endings") return { ...option, variants: [...option.variants, ...dynamic.prompt_endings] };
    if (option.key === "injections") return { ...option, variants: [...option.variants, ...dynamic.injections] };
    if (option.key === "output_prompt_directions") return { ...option, variants: [...option.variants, ...dynamic.output_prompt_directions] };
    return option;
  });
}

function describeAssemblyToken(token) {
  if (token === "base_context" || token === "base_context.text") {
    return { title: "Base Context", detail: "Adds the scene or task framing." };
  }
  if (token === "output_prompt_directions") {
    return { title: "Output Directions", detail: "Adds all output rules for how the model should answer." };
  }
  if (token.startsWith("output_prompt_directions.")) {
    return { title: `Output Direction: ${token.split(".").slice(1).join(".")}`, detail: "Adds one named output-direction block." };
  }
  if (token === "persona.context" || token === "persona.text") {
    return { title: "Persona Context", detail: "Adds the chosen persona's voice or identity." };
  }
  if (token === "persona.base_directives") {
    return { title: "Persona Directives", detail: "Adds the persona's explicit instruction bullets." };
  }
  if (token === "sentiment.context") {
    return { title: "Sentiment Context", detail: "Adds high-level tone framing." };
  }
  if (token === "sentiment.nudges") {
    return { title: "Sentiment Nudges", detail: "Adds short nudges that shape the tone." };
  }
  if (token === "sentiment.examples") {
    return { title: "Sentiment Examples", detail: "Adds examples associated with the sentiment." };
  }
  if (token === "sentiment.scale") {
    return { title: "Sentiment Scale", detail: "Adds sentiment-scale guidance." };
  }
  if (token === "injections") {
    return { title: "Static Injections", detail: "Adds all selected static injection content." };
  }
  if (token.startsWith("injections.")) {
    return { title: `Static Injection: ${token.slice("injections.".length)}`, detail: "Adds one named static injection entry." };
  }
  if (token === "runtime_injections") {
    return { title: "Runtime Injections", detail: "Runs the special runtime injection layer." };
  }
  if (token === "prompt_endings") {
    return { title: "Prompt Endings", detail: "Adds all prompt-ending entries." };
  }
  if (token.startsWith("prompt_endings.")) {
    return { title: `Prompt Ending: ${token.slice("prompt_endings.".length)}`, detail: "Adds one named ending pool." };
  }
  if (token.startsWith("examples[")) {
    return { title: "Dynamic Examples Pool", detail: "Resolves an examples pool from a runtime variable." };
  }
  if (token.startsWith("examples.")) {
    return { title: `Examples: ${token.slice("examples.".length)}`, detail: "Adds one named examples pool." };
  }
  return { title: "Custom Token", detail: "Advanced token preserved exactly as typed." };
}

function assemblyGroups() {
  const dynamic = dynamicAssemblyVariants();

  return [
    {
      title: "Common Tokens",
      items: [
        { token: "base_context", label: "base_context" },
        { token: "base_context.text", label: "base_context.text" },
        { token: "output_prompt_directions", label: "output_prompt_directions" },
        { token: "persona.context", label: "persona.context" },
        { token: "persona.base_directives", label: "persona.base_directives" },
        { token: "sentiment.context", label: "sentiment.context" },
        { token: "sentiment.nudges", label: "sentiment.nudges" },
        { token: "injections", label: "injections" },
        { token: "runtime_injections", label: "runtime_injections" },
        { token: "prompt_endings", label: "prompt_endings" },
      ],
    },
    {
      title: "Named Pools",
      items: [
        ...dynamic.examples.filter((item) => !item.token.startsWith("examples[")),
        ...dynamic.prompt_endings,
        ...dynamic.injections,
        ...dynamic.output_prompt_directions,
      ],
    },
    {
      title: "Dynamic Expressions",
      items: dynamic.examples.filter((item) => item.token.startsWith("examples[")),
    },
  ].filter((g) => g.items.length);
}

function handleAssemblyStepSelection() {
  const select = document.getElementById("assembly-step-select");
  const variantWrap = document.getElementById("assembly-variant-wrap");
  const variantSelect = document.getElementById("assembly-variant-select");
  const help = document.getElementById("assembly-selection-help");
  if (!select || !variantWrap || !variantSelect || !help) return;

  const options = assemblyStepOptions();
  const option = options.find((item) => item.key === select.value) || options[0];
  if (!option) return;

  help.textContent = option.detail;
  const variants = option.variants || [];
  if (variants.length <= 1) {
    variantWrap.hidden = true;
    variantSelect.innerHTML = variants[0]
      ? `<option value="${escapeHtml(variants[0].token)}">${escapeHtml(variants[0].label)}</option>`
      : "";
    return;
  }

  variantWrap.hidden = false;
  variantSelect.innerHTML = variants
    .map((variant) => `<option value="${escapeHtml(variant.token)}">${escapeHtml(variant.label)}</option>`)
    .join("");
}

function addSelectedAssemblyStep() {
  const select = document.getElementById("assembly-step-select");
  const variantWrap = document.getElementById("assembly-variant-wrap");
  const variantSelect = document.getElementById("assembly-variant-select");
  if (!select || !variantWrap || !variantSelect) return;

  const options = assemblyStepOptions();
  const option = options.find((item) => item.key === select.value) || options[0];
  if (!option) return;

  const token = variantWrap.hidden
    ? option.variants?.[0]?.token || ""
    : variantSelect.value;
  addAssemblyToken(token);
}

function addAssemblyTokenFromEncoded(token) {
  addAssemblyToken(decodeURIComponent(token));
}

function renderAssemblyOrderEditor() {
  const host = document.getElementById("assembly-order-list");
  const palette = document.getElementById("assembly-token-groups");
  const hidden = document.getElementById("assembly-order-input");
  const stepSelect = document.getElementById("assembly-step-select");
  if (!host || !palette || !hidden || !stepSelect) return;

  hidden.value = registryState.assembly_order.join(", ");
  stepSelect.innerHTML = assemblyStepOptions()
    .map((option) => `<option value="${escapeHtml(option.key)}">${escapeHtml(option.label)}</option>`)
    .join("");

  if (!registryState.assembly_order.length) {
    host.innerHTML = `<div class="assembly-order-empty">No steps yet. Use Add Step to build the prompt flow.</div>`;
  } else {
    host.innerHTML = registryState.assembly_order
      .map((token, i) => {
        const meta = describeAssemblyToken(token);
        return `<div class="assembly-step-card">` +
          `<div class="assembly-step-number">${i + 1}</div>` +
          `<div class="assembly-step-copy">` +
          `<div class="assembly-step-title">${escapeHtml(meta.title)}</div>` +
          `<div class="assembly-step-detail">${escapeHtml(meta.detail)}</div>` +
          `<div class="assembly-step-token">${escapeHtml(token)}</div>` +
          `</div>` +
          `<span class="assembly-chip-controls">` +
          `<button type="button" class="assembly-chip-btn" onclick="moveAssemblyToken(${i}, -1)" title="Move up">Up</button>` +
          `<button type="button" class="assembly-chip-btn" onclick="moveAssemblyToken(${i}, 1)" title="Move down">Down</button>` +
          `<button type="button" class="assembly-chip-btn" onclick="removeAssemblyToken(${i})" title="Remove">Remove</button>` +
          `</span></div>`;
      })
      .join("");
  }

  palette.innerHTML = assemblyGroups()
    .map(
      (group) =>
        `<div class="assembly-group">` +
        `<div class="assembly-group-title">${escapeHtml(group.title)}</div>` +
        `<div class="assembly-group-items">` +
        group.items
          .map(
            (item) =>
              `<button type="button" class="assembly-palette-btn" onclick="addAssemblyTokenFromEncoded('${encodeURIComponent(item.token)}')">${escapeHtml(item.label)}</button>`
          )
          .join("") +
        `</div></div>`
    )
    .join("");

  handleAssemblyStepSelection();
}

function openModal(key) {
  currentModalContext = key;
  document.getElementById("modal-input").value = "";
  document.getElementById("modal-title").textContent = `${SECTION_LABELS[key]} Variables`;
  document.getElementById("modal-overlay").style.display = "flex";
  setTimeout(() => document.getElementById("modal-input").focus(), 50);
}

function closeModal() {
  document.getElementById("modal-overlay").style.display = "none";
  currentModalContext = null;
}

function saveModal() {
  if (!currentModalContext) return;
  const key = currentModalContext;
  const val = document.getElementById("modal-input").value.trim();
  if (val && !registryState.sections[key].template_vars.includes(val)) {
    registryState.sections[key].template_vars.push(val);
  }
  initApp();
  closeModal();
}

function removeVar(key, varName) {
  registryState.sections[key].template_vars = registryState.sections[key].template_vars.filter((v) => v !== varName);
  initApp();
}

function updateSectionStatus(key, isRequired) {
  registryState.sections[key].required = isRequired;
  exportFullModel();
}

function addEntry(type) {
  const entry = { _ui_id: Date.now() + Math.random() };
  if (type === "runtime_injections") {
    entry.id = "new_injection";
    entry.required = true;
    entry.include_sections = SECTION_KEYS.filter((k) => k !== "runtime_injections");
  } else if (type === "personas") {
    entry.id = "";
    entry.text = "";
    entry.base_directives = [];
  } else if (type === "sentiment") {
    entry.id = "";
    entry.context = "";
    entry.nudges = [];
    entry.examples = [];
  } else if (
    type === "static_injections" ||
    type === "output_prompt_directions" ||
    type === "base_context"
  ) {
    entry.name = "";
    entry.text = "";
  } else {
    entry.name = "";
    entry.items = [];
  }
  registryState.sections[type].items.push(entry);
  renderItems(type);
  exportFullModel();
}

function renderItems(type) {
  const container = document.getElementById(`${type}-container`);
  container.innerHTML = "";

  registryState.sections[type].items.forEach((entry) => {
    const card = document.createElement("div");
    card.className = "entry-card";
    let html = "";

    if (type === "runtime_injections") {
      html = `
        <div class="grid grid-cols-2 gap-3 mb-4">
          <div>
            <label>Injection ID</label>
            <input type="text" value="${entry.id || ""}" oninput="updateField('${type}', ${entry._ui_id}, 'id', this.value)">
          </div>
          <div>
            <label>Strict Requirement</label>
            <select onchange="updateField('${type}', ${entry._ui_id}, 'required', this.value === 'true')">
              <option value="true" ${entry.required ? "selected" : ""}>True</option>
              <option value="false" ${!entry.required ? "selected" : ""}>False</option>
            </select>
          </div>
        </div>
        <div>
          <label>Apply to Sections</label>
          <div class="checkbox-grid">
            ${SECTION_KEYS.filter((k) => k !== "runtime_injections")
              .map(
                (secKey) => `
              <label class="checkbox-item">
                <input type="checkbox" ${(entry.include_sections || []).includes(secKey) ? "checked" : ""}
                  onchange="toggleIncludeSection(${entry._ui_id}, '${secKey}', this.checked)">
                ${SECTION_LABELS[secKey]}
              </label>`
              )
              .join("")}
          </div>
        </div>
      `;
    } else if (type === "personas") {
      html = `
        <label>ID</label>
        <input type="text" value="${entry.id || ""}" oninput="updateField('${type}', ${entry._ui_id}, 'id', this.value)" class="mb-2">
        <label>Context</label>
        <textarea oninput="updateField('${type}', ${entry._ui_id}, 'text', this.value)">${entry.text || ""}</textarea>
        <label class="mt-2">Base Directives</label>
        <textarea oninput="updateField('${type}', ${entry._ui_id}, 'base_directives', this.value)">${(entry.base_directives || []).join("\n")}</textarea>
      `;
    } else if (type === "sentiment") {
      html = `
        <label>ID</label>
        <input type="text" value="${entry.id || ""}" oninput="updateField('${type}', ${entry._ui_id}, 'id', this.value)" class="mb-2">
        <label>Context</label>
        <input type="text" value="${entry.context || ""}" oninput="updateField('${type}', ${entry._ui_id}, 'context', this.value)" class="mb-2">
        <div class="grid grid-cols-2 gap-3 mt-2">
          <div>
            <label>Nudges (One Per Line)</label>
            <textarea rows="4" oninput="updateField('${type}', ${entry._ui_id}, 'nudges', this.value)">${(entry.nudges || []).join("\n")}</textarea>
          </div>
          <div>
            <label>Examples (One Per Line)</label>
            <textarea rows="4" oninput="updateField('${type}', ${entry._ui_id}, 'examples', this.value)">${(entry.examples || []).join("\n")}</textarea>
          </div>
        </div>
      `;
    } else if (type === "examples" || type === "prompt_endings") {
      html = `
        <label>Name</label>
        <input type="text" value="${entry.name || ""}" oninput="updateField('${type}', ${entry._ui_id}, 'name', this.value)" class="mb-2">
        <label>Items</label>
        <textarea oninput="updateField('${type}', ${entry._ui_id}, 'items', this.value)">${(entry.items || []).join("\n")}</textarea>
      `;
    } else {
      html = `
        <label>Name/ID</label>
        <input type="text" value="${entry.name || entry.id || ""}" oninput="updateField('${type}', ${entry._ui_id}, 'name', this.value)" class="mb-2">
        <label>Text Content</label>
        <textarea oninput="updateField('${type}', ${entry._ui_id}, 'text', this.value)">${entry.text || ""}</textarea>
      `;
    }

    card.innerHTML = `<button onclick="removeEntry('${type}', ${entry._ui_id})" class="btn-delete">REMOVE</button>${html}`;
    container.appendChild(card);
  });
}

function toggleIncludeSection(uiId, secKey, isChecked) {
  const entry = registryState.sections.runtime_injections.items.find((e) => e._ui_id === uiId);
  if (!entry) return;
  entry.include_sections = entry.include_sections || [];
  if (isChecked) {
    if (!entry.include_sections.includes(secKey)) entry.include_sections.push(secKey);
  } else {
    entry.include_sections = entry.include_sections.filter((k) => k !== secKey);
  }
  exportFullModel();
}

function updateField(type, uiId, field, value) {
  const entry = registryState.sections[type].items.find((e) => e._ui_id === uiId);
  if (!entry) return;
  if (["base_directives", "nudges", "items", "examples"].includes(field)) {
    entry[field] = String(value)
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
  } else {
    entry[field] = value;
  }
  exportFullModel();
}

function removeEntry(type, uiId) {
  registryState.sections[type].items = registryState.sections[type].items.filter((e) => e._ui_id !== uiId);
  renderItems(type);
  exportFullModel();
}

function applyRegistryJson(json) {
  const reg = json.registry || json || {};
  const next = createEmptyRegistryState();

  next.version = reg.version || 22;
  next.title = reg.title || "Twitch Chatter";
  next.description = reg.description || "";
  next.assembly_order = Array.isArray(reg.assembly_order) ? [...reg.assembly_order] : [];
  next.generation = reg.generation && typeof reg.generation === "object" ? reg.generation : {};
  next.output_policy = reg.output_policy && typeof reg.output_policy === "object" ? reg.output_policy : {};
  if (
    next.output_policy &&
    Array.isArray(next.output_policy.required_patterns) &&
    !Array.isArray(next.output_policy.require_patterns)
  ) {
    next.output_policy.require_patterns = [...next.output_policy.required_patterns];
  }
  next.generationExtras = { ...next.generation };
  next.outputPolicyExtras = { ...next.output_policy };

  for (const [key] of GEN_FIELDS) delete next.generationExtras[key];
  delete next.outputPolicyExtras.min_length;
  delete next.outputPolicyExtras.max_length;
  delete next.outputPolicyExtras.collapse_whitespace;
  delete next.outputPolicyExtras.append_suffix;
  delete next.outputPolicyExtras.required_patterns;
  for (const [key] of POLICY_LIST_FIELDS) delete next.outputPolicyExtras[key];

  const knownTopLevel = new Set([
    "version",
    "title",
    "description",
    "assembly_order",
    "generation",
    "output_policy",
    ...SECTION_KEYS,
  ]);
  for (const [k, v] of Object.entries(reg)) {
    if (!knownTopLevel.has(k)) next.extraTopLevel[k] = v;
  }

  SECTION_KEYS.forEach((key) => {
    const importedSection = reg[key] || {};
    const { required, template_vars, items, ...extras } = importedSection;
    next.sections[key] = {
      required: required !== undefined ? required : next.sections[key].required,
      template_vars: Array.isArray(template_vars) ? [...template_vars] : [],
      extras,
      items: (items || []).map((item) => {
        const entry = { ...item, _ui_id: Date.now() + Math.random() };
        if (key === "personas" && entry.context) entry.text = entry.context;
        if (key === "runtime_injections" && !entry.include_sections) entry.include_sections = [];
        return entry;
      }),
    };
  });

  registryState = next;

  document.getElementById("model-version").value = registryState.version;
  document.getElementById("model-title-input").value = registryState.title;
  document.getElementById("model-desc-input").value = registryState.description;
  for (const [key, id] of GEN_FIELDS) {
    const el = document.getElementById(id);
    if (el) el.value = registryState.generation[key] ?? "";
  }
  document.getElementById("policy-min-length").value = registryState.output_policy.min_length ?? "";
  document.getElementById("policy-max-length").value = registryState.output_policy.max_length ?? "";
  document.getElementById("policy-collapse-whitespace").checked = !!registryState.output_policy.collapse_whitespace;
  document.getElementById("policy-append-suffix").value = registryState.output_policy.append_suffix ?? "";
  for (const [key, id] of POLICY_LIST_FIELDS) {
    const el = document.getElementById(id);
    if (el) el.value = Array.isArray(registryState.output_policy[key]) ? registryState.output_policy[key].join("\n") : "";
  }

  initApp();
}

async function loadBuilderExample() {
  try {
    const res = await fetch("/static/builder-examples/support_bot.json");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    applyRegistryJson(await res.json());
    setValidationStatus("Example loaded.", true);
  } catch (e) {
    console.error(e);
    alert("Failed to load example. Check console for details.");
  }
}

function importModel() {
  const raw = prompt("Paste Registry JSON:");
  if (!raw) return;
  try {
    applyRegistryJson(JSON.parse(raw));
  } catch (e) {
    console.error(e);
    alert("Import failed. Check console for details.");
  }
}

async function validateRegistry() {
  const payload = exportFullModel();
  if (!payload) return;
  try {
    const res = await fetch("/api/registry/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ registry: payload.registry }),
    });
    const text = await res.text();
    if (!res.ok) throw new Error(text || `HTTP ${res.status}`);
    setValidationStatus("Validated by promptlibretto.", true);
  } catch (err) {
    setValidationStatus(`Validation failed: ${err.message}`, false);
  }
}

function consumeStudioHandoff() {
  try {
    const raw = localStorage.getItem(BUILDER_INBOX_KEY);
    if (!raw) return false;
    localStorage.removeItem(BUILDER_INBOX_KEY);
    applyRegistryJson(JSON.parse(raw));
    setValidationStatus("Loaded registry from Studio.", true);
    return true;
  } catch (err) {
    console.warn("Failed to load Studio handoff:", err);
    return false;
  }
}

function openInStudio() {
  const payload = exportFullModel();
  if (!payload) return;
  try {
    localStorage.setItem(STUDIO_INBOX_KEY, JSON.stringify(payload));
    window.location.href = "/";
  } catch (err) {
    alert(`Failed to pass registry to Studio: ${err.message}`);
  }
}

async function copyToClipboard() {
  const text = document.getElementById("output-json").textContent;
  try {
    await navigator.clipboard.writeText(text);
    document.getElementById("copy-btn").textContent = "COPIED!";
  } catch {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    document.body.appendChild(textArea);
    textArea.select();
    document.execCommand("copy");
    document.body.removeChild(textArea);
    document.getElementById("copy-btn").textContent = "COPIED!";
  }
  setTimeout(() => {
    document.getElementById("copy-btn").textContent = "Copy JSON";
  }, 1000);
}

function initApp() {
  const list = document.getElementById("section-list");
  list.innerHTML = "";

  SECTION_KEYS.forEach((key) => {
    const config = registryState.sections[key];
    const section = document.createElement("div");
    section.className = "glass rounded-xl overflow-hidden border border-white/10";
    section.id = `section-${key}`;

    const varBadges = (config.template_vars || [])
      .map(
        (v) =>
          `<span class="var-badge" title="Click to remove" onclick="event.stopPropagation(); removeVar('${key}', '${v}')">${v}</span>`
      )
      .join(" ");

    section.innerHTML = `
      <div class="section-header font-bold" onclick="toggleSection(this.parentElement)">
        <div class="flex items-center gap-3">
          <svg class="chevron w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>
          <div class="flex flex-col">
            <span class="text-sm">${SECTION_LABELS[key]}</span>
            <div id="vars-display-${key}" class="flex gap-1 mt-1">${varBadges}</div>
          </div>
        </div>
        <div class="flex items-center gap-4">
          <button onclick="event.stopPropagation(); openModal('${key}')" class="text-[10px] text-purple-400 hover:underline">+ Add Var</button>
          <span class="text-[10px] text-slate-500 uppercase tracking-widest px-2">${config.items.length} Items</span>
        </div>
      </div>
      <div class="collapsible-content">
        <div class="section-settings">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-4">
              <div class="w-32">
                <label>Section Usage</label>
                <select onchange="updateSectionStatus('${key}', this.value === 'true')">
                  <option value="true" ${config.required ? "selected" : ""}>Mandatory</option>
                  <option value="false" ${!config.required ? "selected" : ""}>Optional</option>
                </select>
              </div>
              <div class="text-[10px] text-slate-500 pt-4 italic">
                Stored within registry.${key}
              </div>
            </div>
          </div>
        </div>
        <div id="${key}-container" class="p-4"></div>
        <div class="p-4 pt-0">
          <button onclick="addEntry('${key}')" class="btn-add">+ Add ${SECTION_LABELS[key]} Entry</button>
        </div>
      </div>
    `;
    list.appendChild(section);
    renderItems(key);
  });

  renderAssemblyOrderEditor();
  switchBuilderTab(activeBuilderTab);
  exportFullModel();
}

consumeStudioHandoff();
initApp();

window.toggleSection = toggleSection;
window.openModal = openModal;
window.closeModal = closeModal;
window.saveModal = saveModal;
window.removeVar = removeVar;
window.updateSectionStatus = updateSectionStatus;
window.addEntry = addEntry;
window.toggleIncludeSection = toggleIncludeSection;
window.updateField = updateField;
window.removeEntry = removeEntry;
window.exportFullModel = exportFullModel;
window.importModel = importModel;
window.loadBuilderExample = loadBuilderExample;
window.copyToClipboard = copyToClipboard;
window.validateRegistry = validateRegistry;
window.openInStudio = openInStudio;
window.toggleBuilderCollapse = toggleBuilderCollapse;
window.switchBuilderTab = switchBuilderTab;
window.addAssemblyToken = addAssemblyToken;
window.addAssemblyTokenFromEncoded = addAssemblyTokenFromEncoded;
window.addCustomAssemblyToken = addCustomAssemblyToken;
window.removeAssemblyToken = removeAssemblyToken;
window.moveAssemblyToken = moveAssemblyToken;
window.handleAssemblyStepSelection = handleAssemblyStepSelection;
window.addSelectedAssemblyStep = addSelectedAssemblyStep;
