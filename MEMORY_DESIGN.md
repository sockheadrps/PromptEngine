# promptlibretto — memory layer design

## Goal

Add a local-first, persistent memory system to the library that:

- Retrieves semantically relevant past context before each generation
- Routes that context into the right registry slots (injections, persona, sentiment)
- Maintains an evolving personality layer that grows over time
- Ships as an optional library extension, not a web-only feature
- Reflects in the Builder and Studio but is not owned by them

---

## Guiding principles

- The registry stays static. `MemoryEngine` produces a mutated `RegistryState` and hands it to the existing `Engine`. No changes to the core hydration pipeline.
- Everything runs locally. Embeddings come from Ollama (`/api/embed`). The vector store is a single SQLite file via `sqlite-vec`. No cloud, no server, no docker.
- The library owns the logic. The web app reflects it. If memory works from the CLI, it works in the studio automatically.

---

## Stack

| Concern | Choice | Why |
|---|---|---|
| Embeddings | Ollama `/api/embed` | Already connected, no new infra, models like `nomic-embed-text` run locally |
| Vector store | `sqlite-vec` | Single `.db` file, zero config, `pip install sqlite-vec` |
| Tag extraction | Small classifier LLM call | Smarter than hard-coded rules, uses existing Ollama connection |
| Personality store | JSON file on disk | Human-readable, easy to edit, version-controllable |

Install:

```bash
pip install "promptlibretto[memory]"   # adds sqlite-vec
ollama pull nomic-embed-text           # or mxbai-embed-large
```

---

## Architecture

```
user input
    │
    ▼
┌──────────────────────────────────────────────────────┐
│                    MemoryEngine                      │
│                                                      │
│  1. embed(input) → vector                            │
│  2. store.retrieve(vector, top_k)                    │  ← MemoryStore (sqlite-vec turns)
│  3. episode_store.retrieve(vector, top_k) [optional] │  ← EpisodeStore (compressed sessions)
│  4. classifier_call(input, chunks)                   │  ← OllamaProvider (small model)
│     → tags: ["past_conflict", ...]                   │
│  5. router.mutate(base_state, tags)                  │  ← Router (registry rules)
│     → (RegistryState, emotion_deltas, debt_effects)  │
│  6. debt.apply(debt_effects) [optional]              │  ← MemoryDebtLayer (JSON file)
│  7. personality.merge(state) [optional]              │  ← PersonalityLayer (JSON file)
│  8. emotional_state.apply_deltas_and_decay()         │  ← EmotionalStateLayer (JSON file)
│  9. inject template vars into state                  │  ← memory_recall, emotional_state,
│                                                      │     relationship_context, etc.
│ 10. engine.hydrate(state)                            │  ← existing Engine (unchanged)
│ 11. provider.generate(prompt)                        │
│ 12. store.upsert(input, response)                    │  ← write turn back to memory
│ 13. working_notes.update() [background]              │  ← fire-and-forget side call
│ 14. relationship.reflect() [background, optional]    │  ← RelationshipLayer (JSON file)
│                                                      │
└──────────────────────────────────────────────────────┘
    │
    ▼
GenerationResult (same shape as today)
```

---

## Module layout

```
promptlibretto/
  memory/
    __init__.py          # exports everything below
    embedder.py          # OllamaEmbedder — POST /api/embed → float[]
    store.py             # MemoryStore — sqlite-vec: upsert, retrieve, forget
    personality.py       # PersonalityLayer — load / amend / save base context JSON
    classifier.py        # Classifier — tag extraction via small LLM call
    router.py            # Router — tag → RegistryState mutations + emotion deltas + debt effects
    working_notes.py     # WorkingNotesLayer — running per-participant notes updated every N turns
    system_summary.py    # SystemSummaryLayer — compressed system prompt updated every N turns
    emotional_state.py   # EmotionalStateLayer — per-participant emotion vector, decay per turn
    debt.py              # MemoryDebtLayer — persistent open-thread list, opened/closed by rules
    episode.py           # EpisodeStore — compressed session summaries, second retrieval tier
    relationship.py      # RelationshipLayer — cross-session relationship arc, background reflections
    engine.py            # MemoryEngine — orchestrates all of the above
    ws_embedder.py       # WsEmbedder — delegates embed calls to a browser WebSocket
    ws_provider.py       # WsProvider — delegates chat calls to a browser WebSocket
```

---

## Component specs

### `OllamaEmbedder`

```python
class OllamaEmbedder:
    def __init__(self, base_url: str, model: str = "nomic-embed-text", client=None)

    async def embed(self, text: str) -> list[float]
    async def embed_batch(self, texts: list[str]) -> list[list[float]]
```

Hits `POST /api/embed` on the existing Ollama instance. Returns raw float vectors.
No new connection config needed — reuses the same base URL as `OllamaProvider`.

---

### `MemoryStore`

```python
class MemoryStore:
    def __init__(self, db_path: str, embedder: OllamaEmbedder, dimensions: int = 768)

    async def upsert(self, turn: MemoryTurn) -> None
    async def retrieve(self, query: str, top_k: int = 5) -> list[MemoryChunk]
    async def forget(self, turn_id: str) -> None
    def close(self) -> None
```

**`MemoryTurn`** — what gets written after each exchange:

```python
@dataclass
class MemoryTurn:
    id: str                      # uuid
    session_id: str
    role: str                    # "user" | "assistant"
    text: str
    tags: list[str]              # extracted by classifier
    timestamp: str               # ISO
    metadata: dict               # arbitrary — persona used, sentiment, slider value, etc.
```

**`MemoryChunk`** — what comes back from retrieval:

```python
@dataclass
class MemoryChunk:
    turn: MemoryTurn
    score: float                 # cosine similarity
```

**Schema (sqlite-vec):**

```sql
CREATE TABLE memory_turns (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    role TEXT,
    text TEXT,
    tags TEXT,          -- JSON array
    timestamp TEXT,
    metadata TEXT       -- JSON object
);

CREATE VIRTUAL TABLE memory_vss USING vec0(
    turn_id TEXT,
    embedding FLOAT[768]
);
```

Retrieve = embed query → `vec0` cosine search → join back to `memory_turns`.

---

### `Classifier`

A single LLM call that reads the retrieved chunks and the current input, then
returns a list of tags. Tags are defined in the registry's memory rules — the
classifier only returns tags it recognises from that vocabulary.

```python
class Classifier:
    def __init__(self, provider: ProviderAdapter, model: str)

    async def extract_tags(
        self,
        user_input: str,
        chunks: list[MemoryChunk],
        known_tags: list[str],         # vocabulary from registry memory rules
    ) -> list[str]
```

Prompt shape (not user-visible, generated internally):

```
You are a context classifier. Given the user's message and relevant past
exchanges, return only the tags from this list that apply:
{known_tags}

User message: {input}

Relevant past exchanges:
{chunks}

Reply with a JSON array of matching tags only. No explanation.
```

Uses a small, fast model (e.g. `llama3.2:1b` or `phi3:mini`). The response is
parsed as JSON; anything that fails to parse returns `[]` gracefully.

---

### `Router`

Maps extracted tags to `RegistryState` mutations. Rules are defined in the
registry under a new top-level key `memory_rules`.

```python
class Router:
    def __init__(self, rules: list[MemoryRule])

    def mutate(self, base_state: RegistryState, tags: list[str]) -> RegistryState
```

**`MemoryRule`** (stored in registry JSON):

```json
{
  "tag": "past_conflict",
  "actions": [
    { "type": "inject",   "section": "runtime_injections", "item": "conflict_context" },
    { "type": "sentiment","value": "tense" }
  ]
}
```

Supported action types:

| type | effect |
|---|---|
| `inject` | adds a named `runtime_injections` or `static_injections` item to the active set |
| `persona` | overrides the persona selection |
| `sentiment` | overrides the sentiment selection |
| `template_var` | sets a template variable value |

Rules are evaluated in order. Later rules can override earlier ones.
Conflicts (two rules setting the same field) are resolved last-wins.

---

### `PersonalityLayer`

A mutable base context that lives in a separate JSON file alongside the registry.
Starts from a seed, accumulates amendments over time.

```python
class PersonalityLayer:
    def __init__(self, path: str)

    def load(self) -> PersonalityProfile
    def merge_into_state(self, state: RegistryState) -> RegistryState
    async def amend(self, session_turns: list[MemoryTurn], provider: ProviderAdapter) -> None
    def save(self) -> None
```

**`PersonalityProfile`** (the JSON file):

```json
{
  "version": 1,
  "seed": "Base personality description set at creation.",
  "amendments": [
    {
      "timestamp": "2026-04-29T...",
      "text": "Tends to deflect when asked about past failures.",
      "source_session": "abc123"
    }
  ],
  "assembled": "Base personality description... Tends to deflect..."
}
```

`assembled` is pre-built by concatenating seed + amendments. `merge_into_state`
injects it as a `template_var` that maps to a `{personality_context}` placeholder
in the registry's `base_context`.

**Amendment flow** (runs post-session, optional):

After a session ends, `amend()` sends the last N turns to the LLM with a prompt
like:

```
Given this conversation, what did you learn about this character's personality,
preferences, or tendencies that isn't already captured in the current profile?
Reply with a single concise observation, or "nothing new" if there's nothing to add.

Current profile: {assembled}
Conversation: {turns}
```

If the response isn't "nothing new", it's appended as a new amendment entry.

---

### `WorkingNotesLayer`

A running scratchpad maintained by a periodic side-call to the participant's own
model. Captures how the conversation is going from the participant's perspective —
updated every N session turns in the background so it never blocks generation.

```python
class WorkingNotesLayer:
    def __init__(self, path: str)

    def load(self) -> WorkingNotes
    @property def notes(self) -> WorkingNotes       # lazy-loads
    @property def text(self) -> str                 # shortcut for notes.text
    def save(self) -> None
    def clear(self) -> None

    async def update(
        self,
        recent_turns: list[MemoryTurn],
        provider: ProviderAdapter,
        model: str,
        max_tokens: int = 200,
        persona: str | None = None,
        self_name: str = "you",
        other_name: str = "the other person",
        about_me_prompt: str | None = None,
        about_other_prompt: str | None = None,
    ) -> bool
```

**`WorkingNotes`** (the JSON file):

```json
{
  "text": "ABOUT ME:\n...\n\nABOUT OTHER:\n...",
  "last_updated": "2026-05-06T...",
  "update_count": 4
}
```

Notes are structured in two sections when a persona is provided (in-character
mode): `ABOUT ME` and `ABOUT <OTHER NAME>`. Without a persona the model writes
generic observation bullets. Notes are included in `memory_recall` automatically
when they exist.

**Update timing:** `record_turn()` fires a `asyncio.create_task()` for the update
when `len(session_turns) - last_update_at >= notes_every_n` and both user and
assistant roles are present. Generation is never blocked waiting for notes.

---

### `SystemSummaryLayer`

A periodically-refreshed compressed version of the participant's assembled system
prompt, excluding output-directive sections (which need to stay precise). Reduces
context token usage over long sessions.

```python
class SystemSummaryLayer:
    def __init__(self, path: str)

    def load(self) -> SystemSummary
    @property def summary(self) -> SystemSummary    # lazy-loads
    @property def text(self) -> str
    def save(self) -> None
    def clear(self) -> None

    async def update(
        self,
        full_prompt: str,
        provider: ProviderAdapter,
        model: str,
        max_tokens: int = 300,
        persona: str | None = None,
    ) -> bool
```

**`SystemSummary`** (the JSON file):

```json
{
  "text": "Compressed system prompt...",
  "last_updated": "2026-05-06T...",
  "update_count": 2,
  "source_chars": 1840
}
```

`record_system_prompt()` is called by the ensemble engine after each turn with
the full assembled system prompt. The summary updates every `system_summary_every_n_turns`
model turns. Like working notes, excluded sections (output directions, base context,
personas, sentiment, static injections) are stripped before compression so the
output stays focused on character and scene.

---

### `MemoryEngine`

The top-level orchestrator. Wraps `Engine` and is the only public API most users
need to touch. The embedder is passed to `MemoryStore`, not to `MemoryEngine` directly.

```python
class MemoryEngine:
    def __init__(
        self,
        engine: Engine,
        store: MemoryStore,
        classifier: Classifier,
        router: Router,
        personality: PersonalityLayer | None = None,
        session_id: str | None = None,
        top_k: int = 5,
        history_window: int = 6,
        working_notes: WorkingNotesLayer | None = None,
        notes_provider: ProviderAdapter | None = None,
        notes_model: str | None = None,
        notes_every_n_turns: int = 3,
        notes_max_tokens: int = 200,
        notes_about_me_prompt: str | None = None,
        notes_about_other_prompt: str | None = None,
        participant_name: str = "you",
        system_summary: SystemSummaryLayer | None = None,
        system_summary_every_n_turns: int = 3,
        system_summary_max_tokens: int = 300,
        system_summary_skip_section_keys: list[str] | None = None,
        use_classifier: bool = True,
        auto_inject: bool = False,        # see Auto-inject below
    )

    # Public properties (access the layer objects directly)
    @property def working_notes(self) -> WorkingNotesLayer | None
    @property def system_summary(self) -> SystemSummaryLayer | None

    async def prepare(
        self,
        user_input: str,
        base_state: RegistryState | dict | None = None,
        *,
        other_name: str | None = None,
    ) -> PreparedMemoryState

    async def run(
        self,
        user_input: str,
        base_state: RegistryState | dict | None = None,
        *,
        route: str | None = None,
        seed: int | None = None,
    ) -> MemoryGenerationResult

    async def record_turn(
        self,
        text: str,
        role: str,
        tags: list[str] | None = None,
        metadata: dict | None = None,
    ) -> MemoryTurn

    async def record_system_prompt(self, full_prompt: str) -> None

    async def end_session(
        self,
        provider_model: str | None = None,
    ) -> bool
```

`prepare()` returns a `PreparedMemoryState` without generating — useful when the
caller owns the generation step (e.g. streaming, Ensemble). `run()` calls
`prepare()` → `engine.run()` → `record_turn()` for both user and assistant turns.

**`PreparedMemoryState`**:

```python
@dataclass
class PreparedMemoryState:
    state: RegistryState
    chunks: list[MemoryChunk]
    tags: list[str]
    applied: list[str]
    clf: ClassifierResult | None
    auto_inject_recall: str = ""   # non-empty when auto_inject is on and no
                                   # registry section declared memory_recall
```

**`MemoryGenerationResult`** extends `GenerationResult`:

```python
@dataclass
class MemoryGenerationResult(GenerationResult):
    retrieved_chunks: list[MemoryChunk]
    extracted_tags: list[str]
    applied_rules: list[str]
    final_state: RegistryState | None
    classifier_stats: dict
```

---

### Template variables injected by `prepare()`

`prepare()` sets these template variables on the state before hydration. A section
must declare the variable name in its `template_vars` list for the value to be
injected there.

| Variable | Content |
|---|---|
| `memory_recall` | Combined block: unresolved debt threads, system summary, working notes, past episode summaries, recent conversation, retrieved cross-session chunks |
| `emotional_state` | Current emotional state as human-readable text (e.g. "warmth: high, tension: moderate") |
| `relationship_context` | Accumulated relationship arc observations, formatted as "Relationship arc:\n- I've noticed…" |
| `working_notes` | Running notes text only (without history or retrieved chunks) |
| `system_summary` | Compressed system prompt text (empty string if no summary exists yet) |
| `user_input` | The current user message |
| `rule_ending` | Ending text from any matched memory rule |
| `other_name` | The other participant's name (Ensemble only) |
| `thoughts_about_other` | Retrieved chunks about the other speaker (Ensemble only) |

**`memory_recall` is the recommended way to expose memory context.** It
automatically includes all active sub-layers (working notes, system summary,
debt threads, episode summaries) when they exist, so a single `{memory_recall}`
placeholder covers everything. Use the individual vars only when you need them
in a different position in the prompt.

**`system_summary` injects the actual compressed text** (not an empty string).
Previously this was intentionally blank because summary was embedded in
`memory_recall`; now both work independently so registries can place them
wherever makes sense.

---

### Auto-inject

When `auto_inject: true` is set in `memory_config` (or passed to `MemoryEngine`),
and `prepare()` finds that no registry section declared `memory_recall` in its
`template_vars`, the recall block is returned in `PreparedMemoryState.auto_inject_recall`.
The ensemble engine appends this directly to the system prompt.

This means memory works correctly even in registries that don't have a dedicated
`memory_recall` section. Without `auto_inject`, memory retrieval runs but the
results are silently discarded if no section consumes them.

The flag is off by default to preserve existing behaviour for registries that
manage prompt structure explicitly.

---

## Registry schema additions

Two new optional top-level keys:

```jsonc
{
  "registry": {
    // ... existing fields ...

    "memory_rules": [
      {
        "tag": "past_conflict",
        "description": "The user is referencing a previous disagreement or conflict.",
        "ending_text": "Optional text appended to the prompt when this tag fires.",
        "actions": [
          { "type": "inject",    "section": "runtime_injections", "item": "conflict_note" },
          { "type": "sentiment", "value": "tense" }
        ]
      }
    ],

    "memory_config": {
      "classifier_url":   "http://localhost:11434",
      "classifier_model": "llama3.2:1b",
      "embed_url":        "http://localhost:11434",
      "embed_model":      "nomic-embed-text",
      "top_k":            5,
      "history_window":   6,
      "prune_keep":       200,
      "personality_file": "personality.json",      // relative to registry file
      "working_notes_enabled":         false,
      "working_notes_every_n_turns":   3,
      "working_notes_max_tokens":      200,
      "system_summary_enabled":        false,
      "system_summary_every_n_turns":  3,
      "system_summary_max_tokens":     300,
      "auto_inject":      false                    // append recall when no section declares it
    }
  }
}
```

A minimal registry that wants memory recall in the prompt needs a section like:

```jsonc
"memory_recall": {
  "required": false,
  "template_vars": ["memory_recall"],
  "items": [{ "name": "recall", "text": "{memory_recall}" }]
}
```

Or set `auto_inject: true` in `memory_config` to skip the section entirely.

---

## Builder UI

### Memory Config panel

Memory Config lives in its own full-width panel in the Builder. It is laid out as a 2×2 card grid with four cards:

- **Classifier** — classifier URL, model (with fetch + inline test), `use_classifier` toggle, `auto_inject` toggle
- **Embedding** — embed URL, model (with fetch + inline test), use_embed toggle, dimensions
- **Retrieval** — top_k, history_window, retrieval mode
- **Storage** — personality file, working notes file, system summary file, vector store path, prune_keep

During the new-registry setup flow, Memory Config is the required configuration step when the user chooses to enable memory. The Classifier Rules panel (which maps tags to actions) is only accessible after setup is complete.

### Memory Rules panel

- A collapsible **Memory Rules** section on the Classifiers tab
- Each rule: tag name + description + optional ending_text + a list of actions (type + target)
- Actions built with dropdowns populated from the current registry's sections and items
- Known tags are auto-populated from all rules (used as the classifier vocabulary)

### Per-item `memory_tag` field

- `runtime_injections` and `static_injections` item forms get an optional
  **Memory tag** input — the tag that activates this item

### Ensemble tuning panel

Per-participant memory overrides exposed in the Ensemble tuning tab:

| Control | Override key |
|---|---|
| Working notes checkbox | `working_notes_enabled` |
| Notes every N | `working_notes_every_n_turns` |
| Notes max tokens | `working_notes_max_tokens` |
| Summarize system prompt checkbox | `system_summary_enabled` |
| Summary every N | `system_summary_every_n_turns` |
| Summary max tokens | `system_summary_max_tokens` |
| Auto-inject recall checkbox | `auto_inject` |
| embed_url | `embed_url` |
| embed_path | `embed_path` |

These override the registry's `memory_config` for the current run only and are
sent as `memory_overrides` in the `/api/ensemble/run` request body.

---

## Usage example

```python
import json
from promptlibretto import Engine, OllamaProvider, Registry
from promptlibretto.memory import Classifier, MemoryEngine, MemoryStore, OllamaEmbedder, Router

provider   = OllamaProvider("http://localhost:11434")
embedder   = OllamaEmbedder("http://localhost:11434", model="nomic-embed-text")
reg        = Registry.from_dict(json.load(open("my_character.json")))
engine     = Engine(reg, provider=provider)
store      = MemoryStore("memory.db", embedder=embedder)
classifier = Classifier(provider, model="llama3.2:1b")
router     = Router(rules=engine.registry.memory_rules)

mem_engine = MemoryEngine(
    engine=engine,
    store=store,
    classifier=classifier,
    router=router,
    auto_inject=True,      # works even without a memory_recall section in the registry
)

result = await mem_engine.run("Hey, remember last time when you said...")
print(result.text)
print(result.extracted_tags)   # ["past_conflict", "recall"]
print(result.applied_rules)    # ["past_conflict → inject:conflict_note, sentiment:tense"]

await mem_engine.end_session()
```

Accessing notes and summary after a run:

```python
# Public properties — no private attribute access needed
if mem_engine.working_notes:
    print(mem_engine.working_notes.text)
    print(mem_engine.working_notes.notes.update_count)

if mem_engine.system_summary:
    print(mem_engine.system_summary.text)
    print(mem_engine.system_summary.summary.source_chars)
```

---

## Implementation status

All components are shipped.

1. `OllamaEmbedder` — hits `/api/embed`, returns vectors.
2. `MemoryStore` — sqlite-vec schema, upsert, retrieve, prune, confidence decay/boost.
3. `Classifier` — single LLM call, JSON parse, graceful fallback.
4. `Router` — pure Python, no I/O. Reads `memory_rules` from registry. Returns emotion deltas and debt side-effects alongside mutated state.
5. `MemoryEngine` — orchestrates all layers around the existing `Engine`.
6. `PersonalityLayer` — load/save JSON, post-session amendment call.
7. `WorkingNotesLayer` / `SystemSummaryLayer` — fire-and-forget side-call layers.
8. `EmotionalStateLayer` — per-participant float vector; dimensions decay toward neutral each turn; rules apply deltas; injected as `{emotional_state}`.
9. `MemoryDebtLayer` — persistent JSON list of open threads; rules open/close entries; injected into `memory_recall` as "Unresolved threads".
10. `EpisodeStore` — second sqlite-vec tier in the same `.db`; compresses session turns into a single embedded `Episode` on session end; retrieved episodes appear in `memory_recall` as "Past episodes".
11. `RelationshipLayer` — persistent cross-session relationship arc; background side-call every N turns generates a one-sentence observation; injected as `{relationship_context}`.
12. Registry schema — `memory_rules`, `memory_config` fields live in the registry model.
13. Builder UI — Memory Config tab, memory rules panel, ensemble memory toggles (working notes, system summary, emotional state, debt, episodic, relationship arc).

Steps 1–11 are pure library. Step 12 is a schema addition. Step 13 is UI only.

---

## Decisions

- **Forgetting policy** — sliding window by count. Keep the last N turns
  (default 200, configurable via `prune_keep` in `memory_config`). Pruning is
  explicit via `store.prune()` — nothing is deleted mid-session automatically.
  No TTL; calendar time is irrelevant for conversational context.

- **Multi-character memory** — one store per registry title + participant name.
  The `.db` file lives in a per-title directory under the studio's stores path.
  No shared stores across registries.

- **Ensemble memory** — each participant gets their own `MemoryEngine` and
  their own store. They don't share memory. Cleaner isolation; avoids one
  participant's history bleeding into the other's routing decisions. All turns
  are recorded into every participant's store (own turns as `assistant`, other's
  turns as `user`) so each participant has a complete subjective record.

- **Notes are fire-and-forget** — `record_turn()` schedules notes updates via
  `asyncio.create_task()`. Generation is never blocked waiting for a side call.
  The next `prepare()` picks up whatever the task wrote; if the task is still
  in flight, it picks up the previous notes. Side-call failures are silently
  swallowed — notes are best-effort context, not critical path.

- **Auto-inject vs explicit section** — explicit `memory_recall` sections give
  the registry author control over where in the prompt memory context lands.
  `auto_inject` is a convenience flag for registries that don't need that
  control; it appends recall after the assembled system prompt.

- **Embedding dimensions** — `nomic-embed-text` (768-dim) is the default.
  Dimension is fixed at store creation time. Attempting to upsert a vector
  with the wrong dimension raises a clear error rather than silently corrupting
  the index.

- **Browser-side embed and chat** — in Docker or other environments where the
  server cannot reach Ollama directly, `WsEmbedder` and `WsProvider` delegate
  all model calls to the browser over a WebSocket established before `/run`.
  The server never needs a direct line to the model endpoint.

---

## How memory works — conceptual overview

The model that generates responses has no persistent state. Every time it runs,
it starts fresh with only what's in its context window. Memory is the system that
decides what goes into that window before generation begins.

**The problem memory solves**

A model given a 10-turn conversation will respond coherently within those 10 turns.
But give it a brand-new conversation and it has no idea who the user is, what was
said last week, or what patterns have emerged over dozens of sessions. Memory bridges
that gap by selecting and injecting relevant context before each generation.

**How a turn works, step by step**

When a new message arrives:

1. The message is converted to a vector (a list of numbers that represents its
   meaning). This is done by a small embedding model, not the main LLM.

2. That vector is compared against every stored turn in the database using cosine
   similarity. The closest matches — past messages that are semantically related
   to what was just said — are retrieved. This is the retrieval step.

3. A small, fast classifier LLM reads the current message and the retrieved chunks
   and decides which memory tags apply — labels defined in the registry like
   `"past_conflict"` or `"ancient_magic_confusion"`. Tags are drawn only from the
   vocabulary you defined; the classifier can't invent new ones.

4. Each matched tag triggers router rules that mutate the registry state — switching
   persona, injecting context items, changing sentiment, appending a rule-ending
   directive. The registry itself doesn't change; only the state for this one turn.

5. The retrieved history, working notes, and system summary are formatted and
   injected into the prompt through the `{memory_recall}` template variable (or
   appended directly if `auto_inject` is on).

6. The enriched state is handed to the normal `Engine.hydrate()` pipeline. From
   there on everything works exactly as without memory — the prompt is assembled
   from the registry and the mutated state, and generation runs.

7. After the response is generated, the turn pair is written back to the vector
   store. In the background, working notes may be updated via a side call to the
   participant's own model — this never blocks the response.

**What each memory component does**

| Component | What it holds | When it updates |
|---|---|---|
| **Vector store** | Every turn, as embeddings | After each message |
| **Personality layer** | A growing profile — who this participant is | End of session (optional) |
| **Working notes** | Running scratchpad — how the conversation is going right now | Every N turns, in background |
| **System summary** | Compressed version of the system prompt | Every N turns, in background |

**What memory is not**

Memory does not give the model a longer context window. It selects a small amount
of relevant past context and places it in the existing window. The model still only
sees what fits in its context — memory just makes sure the most relevant things are
there rather than the most recent N turns blindly.

Memory also does not change the model weights. Nothing is trained. The personality
layer and working notes are plain text files that get prepended to the prompt.
Every "memory" the system has is ultimately just text in a prompt.
