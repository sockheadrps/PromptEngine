# Memory Extensions

Six features that evolve the memory layer from retrieval-only toward something that
feels like genuine relational continuity. Each is a self-contained addition to the
existing `promptlibretto/memory/` package.

---

## Status

```
1. Memory Confidence      ✅ shipped  — confidence.py, store decay + boost
2. Memory Debt            ✅ shipped  — new layer, no deps
3. Emotional State Decay  ✅ shipped  — emotional_state.py, router "emotion" actions
4. Reflection Turns       ✅ shipped  — new layer, benefits from personality
5. Style Modulation       ✅ shipped  — style_blend.py, blends on emotional state
6. Episodic Compression   ✅ shipped  — new storage tier, benefits from confidence
```

Feature 5 requires feature 3. Feature 6 is richer with feature 1.
Each feature is described below with: what it is, what changes, and the public interface.

---

## 1. Memory Confidence

### What it is

Every stored turn gets a `confidence` score between 0.0 and 1.0. Confidence
represents how certain the system is that a piece of memory is still true. It
decays with age (old unconfirmed memories become hedged) and strengthens when a
similar claim is retrieved and confirmed by a new turn. The score changes how
memory is rendered: high confidence → declarative ("you love jazz"), low
confidence → hedged ("you seem to enjoy jazz").

### Schema changes

`MemoryTurn` gets a new field:

```python
@dataclass
class MemoryTurn:
    ...
    confidence: float = 1.0
```

SQLite schema:

```sql
ALTER TABLE memory_turns ADD COLUMN confidence REAL DEFAULT 1.0;
```

### New logic

**Age-based decay** — computed at retrieval time, not stored. No periodic update
needed:

```python
def _decayed_confidence(base: float, turns_since: int, decay_rate: float = 0.02) -> float:
    return base * max(0.1, 1.0 - turns_since * decay_rate)
```

`turns_since` = total turns in store minus turn's insertion order index.

**Confirmation boost** — when a retrieved chunk's content overlaps semantically
with the current input (score above a threshold), its stored confidence is bumped:

```python
# In MemoryStore.retrieve(), after cosine search:
if chunk.score > confirmation_threshold:
    store.boost_confidence(chunk.turn.id, delta=0.1, cap=1.0)
```

### Rendering change in `_format_recall()`

```python
def _hedge(text: str, confidence: float) -> str:
    if confidence >= 0.8:
        return text                          # declarative
    elif confidence >= 0.5:
        return f"(possibly) {text}"          # soft hedge
    else:
        return f"(uncertain) {text}"         # explicit uncertainty
```

Applied per chunk when formatting the "Relevant past notes" section.

### New config keys in `memory_config`

```json
{
  "confidence_decay_rate": 0.02,
  "confidence_confirmation_threshold": 0.85,
  "confidence_boost_delta": 0.1
}
```

### New files

- `promptlibretto/memory/confidence.py` — decay + boost helpers

### Changes to existing files

| File | Change |
|---|---|
| `store.py` | Add `confidence` column, `boost_confidence()` method, decay computation in `retrieve()` |
| `engine.py` | Pass decay_rate from config to store |
| `_format_recall()` | Apply `_hedge()` per chunk |
| `ensemble_routes.py` | Read confidence config keys |

---

## 2. Memory Debt

### What it is

Unresolved conversational threads — topics that were opened but never closed. A
separate lightweight JSON file tracks open items. Memory rules can declare that
they open or close a debt. The debt list is surfaced at the top of `memory_recall`
so the participant always knows what's hanging.

Example: a rule tagged `eastern_gate_problem` with `"opens_debt": true` fires when
the user raises the topic. Until a matching rule with `"closes_debt": true` fires,
every subsequent prompt will include: `"Unresolved: eastern gate problem."` That
creates narrative continuity across sessions without any LLM call.

### New dataclass

```python
@dataclass
class DebtEntry:
    tag: str
    description: str       # human-readable label from the rule
    opened_at: str         # ISO timestamp
    session_id: str
    turn_text: str         # the turn that triggered it (truncated)
```

### New layer

```python
class MemoryDebtLayer:
    def __init__(self, path: str)

    def load(self) -> list[DebtEntry]
    def open(self, tag: str, description: str, session_id: str, turn_text: str) -> None
    def close(self, tag: str) -> bool       # True if something was actually closed
    def open_items(self) -> list[DebtEntry]
    def save(self) -> None
    def clear(self) -> None
```

### Registry rule schema change

```json
{
  "tag": "eastern_gate_problem",
  "description": "User is raising the unresolved eastern gate issue.",
  "opens_debt": true,
  "debt_label": "The eastern gate problem was never resolved."
}
```

```json
{
  "tag": "eastern_gate_resolved",
  "description": "The eastern gate issue has been addressed.",
  "closes_debt": "eastern_gate_problem"
}
```

`closes_debt` takes the tag name of the debt to close (can differ from its own
tag). A rule can both close one debt and open another.

### Router changes

`Router.mutate()` currently returns only a mutated `RegistryState`. It needs
access to `MemoryDebtLayer` to open/close entries when rules fire. Two options:

**Option A (preferred):** `Router.mutate()` returns a second value — a list of
debt side-effects — and `MemoryEngine.prepare()` applies them:

```python
mutated, debt_effects = self._router.mutate(state, tags)
for effect in debt_effects:
    if effect["type"] == "open":
        self._debt.open(effect["tag"], effect["label"], self.session_id, user_input)
    elif effect["type"] == "close":
        self._debt.close(effect["tag"])
```

### `MemoryEngine.__init__` change

```python
debt: MemoryDebtLayer | None = None,
```

### `_format_recall()` change

When `debt` is provided and has open items, prepend a block:

```
Unresolved threads:
- The eastern gate problem was never resolved. (opened 2026-05-01)
- You promised to look into the shipment delay. (opened 2026-05-03)
```

### New files

- `promptlibretto/memory/debt.py` — `DebtEntry`, `MemoryDebtLayer`

### Changes to existing files

| File | Change |
|---|---|
| `router.py` | Return debt side-effects list from `mutate()` |
| `engine.py` | Accept `debt` layer, apply effects in `prepare()`, pass debt to `_format_recall()` |
| `ensemble_routes.py` | Build `MemoryDebtLayer`, pass to `MemoryEngine` |
| `_format_recall()` | Prepend open debt items |

---

## 3. Emotional State Decay

### What it is

A per-participant float vector that tracks the current emotional tone of the
conversation. Dimensions are defined in `memory_config` (e.g. `warmth`,
`tension`, `trust`, `playfulness`). Each dimension lives between 0.0 and 1.0,
decaying toward 0.5 (neutral) each turn. Memory rules can apply deltas
(`+0.2 warmth`, `-0.1 trust`) when they fire. The state is injected as a
template variable and can be used to modulate sentiment selection.

### New dataclass

```python
@dataclass
class EmotionalState:
    dimensions: dict[str, float]    # e.g. {"warmth": 0.7, "tension": 0.3}
    last_updated: str
    turn_count: int

    def decay(self, rate: float = 0.05) -> None:
        for k in self.dimensions:
            v = self.dimensions[k]
            self.dimensions[k] = v + (0.5 - v) * rate   # pull toward 0.5

    def apply_delta(self, deltas: dict[str, float]) -> None:
        for k, d in deltas.items():
            if k in self.dimensions:
                self.dimensions[k] = max(0.0, min(1.0, self.dimensions[k] + d))

    def to_text(self) -> str:
        # Converts to human-readable for template injection
        # e.g. "warmth: high, tension: moderate, trust: low"
```

### New layer

```python
class EmotionalStateLayer:
    def __init__(self, path: str, dimensions: list[str])

    def load(self) -> EmotionalState
    @property def state(self) -> EmotionalState
    def save(self) -> None
    def clear(self) -> None
```

### Registry rule schema change

New action type `"emotion"`:

```json
{
  "tag": "user_betrayal",
  "actions": [
    { "type": "emotion", "deltas": { "trust": -0.3, "tension": +0.2 } }
  ]
}
```

### `memory_config` additions

```json
{
  "emotion_dimensions": ["warmth", "tension", "trust", "playfulness"],
  "emotion_decay_rate": 0.05
}
```

### Flow in `MemoryEngine.prepare()`

1. After router mutates state, apply any emotion deltas from matched rules
2. Apply per-turn decay
3. Save state
4. Inject `{emotional_state}` template var as formatted text

```python
# In prepare():
emotion_text = ""
if self._emotional_state is not None:
    for rule_tag in tags:
        rule = self._router.get_rule(rule_tag)
        if rule and rule.emotion_deltas:
            self._emotional_state.state.apply_delta(rule.emotion_deltas)
    self._emotional_state.state.decay(self._emotion_decay_rate)
    self._emotional_state.save()
    emotion_text = self._emotional_state.state.to_text()
```

Template var `emotional_state` is injected alongside `memory_recall` into any
section that declares it.

### New files

- `promptlibretto/memory/emotional_state.py` — `EmotionalState`, `EmotionalStateLayer`

### Changes to existing files

| File | Change |
|---|---|
| `router.py` | Parse `"emotion"` action type, expose rule emotion deltas |
| `engine.py` | Accept `emotional_state` layer, apply + decay in `prepare()`, inject template var |
| `ensemble_routes.py` | Build `EmotionalStateLayer`, pass to `MemoryEngine` |

---

## 4. Reflection Turns

### What it is

A relationship-level summary layer that tracks how the relationship between the
participant and the other speaker is *changing* over time, not just what happened.
Unlike personality (which tracks the participant's own character) and working notes
(which are session-local), reflections are persistent cross-session observations
specifically about the dynamic between the two: trust arc, tone evolution,
recurring patterns.

Every N sessions (or N turns), a side-call generates a short reflection entry:
`"The user has become more open about their frustrations since session 3."` These
accumulate into a `RelationshipLayer` and are injected into the prompt alongside
personality context.

### New dataclasses

```python
@dataclass
class ReflectionEntry:
    text: str
    timestamp: str
    session_id: str
    turn_count_at: int
    valence: str    # "positive" | "negative" | "neutral" — direction of change

@dataclass
class RelationshipProfile:
    other_name: str
    entries: list[ReflectionEntry]
    last_reflected_at: str
    reflect_count: int

    def to_context(self, max_entries: int = 5) -> str
        # Format recent entries as a relationship context block
```

### New layer

```python
class RelationshipLayer:
    def __init__(self, path: str, other_name: str)

    def load(self) -> RelationshipProfile
    @property def profile(self) -> RelationshipProfile
    def save(self) -> None
    def clear(self) -> None

    async def reflect(
        self,
        recent_turns: list[MemoryTurn],
        provider: ProviderAdapter,
        model: str,
        persona: str | None = None,
        self_name: str = "you",
        other_name: str = "them",
        max_tokens: int = 150,
    ) -> bool                               # True if a new entry was added
```

### LLM prompt for reflection

```
You are reviewing a conversation to identify how the relationship between
{self_name} and {other_name} has changed.

{persona if present}

Recent conversation:
{turns}

Existing relationship observations:
{entries}

Write a single sentence describing a meaningful change in the relationship
dynamic — something new that isn't already captured above. Write in first
person from {self_name}'s perspective, past tense. Begin with "I've noticed"
or "I'm starting to" or "It feels like". If nothing meaningful has changed,
reply with "nothing new".
```

### `memory_config` additions

```json
{
  "relationship_enabled": false,
  "relationship_reflect_every_n_turns": 10,
  "relationship_max_tokens": 150,
  "relationship_max_entries": 20
}
```

### Flow

Reflection fires in `record_turn()` (same pattern as working notes) as a
background task. `prepare()` injects `{relationship_context}` as a template var
using `profile.to_context()`.

### New files

- `promptlibretto/memory/relationship.py` — `ReflectionEntry`, `RelationshipProfile`, `RelationshipLayer`

### Changes to existing files

| File | Change |
|---|---|
| `engine.py` | Accept `relationship` layer, schedule reflection task in `record_turn()`, inject template var in `prepare()` |
| `ensemble_routes.py` | Build `RelationshipLayer` per participant, pass to `MemoryEngine` |

---

## 5. Continuous Style Modulation

### What it is

Rather than snapping to a single persona or sentiment item, the system blends
between items based on the current emotional state (from feature 3). A warmth
score of 0.8 might select `mystically_reassuring` 80% of the time and
`burned_out_mage` 20% of the time. In practice: both items' text is included,
with the secondary item's contribution weighted and truncated.

This requires feature 3 (emotional state) to be built first. The emotional
dimensions map to persona/sentiment selections via a config table.

### New config in `memory_config`

```json
{
  "style_modulation_enabled": false,
  "style_emotion_map": {
    "personas": {
      "warmth": {
        "low":  "burned_out_mage",
        "high": "mystically_reassuring"
      }
    },
    "sentiment": {
      "tension": {
        "low":  "mystically_reassuring",
        "high": "nervous_helpful"
      }
    }
  }
}
```

Each dimension maps to a section and two item IDs for the low/high poles. The
blend weight is the dimension's current value.

### How blending works

`_compute_style_blend(emotional_state, style_map)` returns a list of
`(section_key, item_id, weight)` tuples. The two highest-weight items per section
are included. Weight determines how much of the item's text appears.

For initial implementation: select the dominant item normally (via state mutation),
then append the secondary item's text at reduced length (e.g. first sentence only)
under a soft separator. This avoids changing the hydration pipeline.

```python
# In prepare(), after personality merge:
if self._style_modulation and self._emotional_state:
    blends = _compute_style_blend(
        self._emotional_state.state,
        self._style_map,
    )
    mutated = _apply_style_blend(mutated, blends, engine.registry)
```

`_apply_style_blend` selects primary item normally, appends secondary as an
additional selected item with a weight annotation. The section renders both,
with the secondary item's text truncated to a configurable character limit.

### Phase 2 (after initial implementation)

Replace text truncation with an LLM blend call: given two character descriptions
at a specified ratio, generate a single blended description. This is higher quality
but adds a side-call per turn. Phase 1 (concatenation) ships first.

### New files

- `promptlibretto/memory/style_blend.py` — `_compute_style_blend()`, `_apply_style_blend()`

### Changes to existing files

| File | Change |
|---|---|
| `engine.py` | Accept `style_map` config, call blend in `prepare()` after personality merge |
| `ensemble_routes.py` | Read `style_emotion_map` from config, pass to `MemoryEngine` |

**Dependency:** Feature 3 (emotional state) must be implemented first.

---

## 6. Episodic Compression

### What it is

A second storage tier above individual turns. After a session ends (or every N
turns), recent turns are compressed by an LLM into a single `Episode` — a dense
semantic summary with its own embedding. Retrieval searches both the turn store
and the episode store. Episodes surface older, compressed history that would
otherwise require retrieving dozens of individual turns.

This moves the memory model from "retrieve messages" to "retrieve episodes" for
anything beyond the current session, while keeping recent turns as-is.

### New dataclass

```python
@dataclass
class Episode:
    id: str
    session_id: str
    start_turn_index: int
    end_turn_index: int
    summary_text: str
    embedding: list[float]
    timestamp: str
    tags: list[str]            # union of tags from compressed turns
    confidence: float = 1.0   # inherits from feature 1 if available
    turn_count: int = 0
```

### New SQLite table (same `.db` file)

```sql
CREATE TABLE memory_episodes (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    start_turn_index INTEGER,
    end_turn_index INTEGER,
    summary_text TEXT,
    tags TEXT,          -- JSON array
    timestamp TEXT,
    confidence REAL DEFAULT 1.0,
    turn_count INTEGER DEFAULT 0
);

CREATE VIRTUAL TABLE episode_vss USING vec0(
    episode_id TEXT,
    embedding FLOAT[768]
);
```

### New class

```python
class EpisodeStore:
    def __init__(self, db_path: str, embedder: OllamaEmbedder)

    async def compress(
        self,
        turns: list[MemoryTurn],
        provider: ProviderAdapter,
        model: str,
        max_tokens: int = 200,
    ) -> Episode | None

    async def retrieve(
        self,
        query: str,
        top_k: int = 3,
    ) -> list[EpisodeChunk]

    def recent(self, limit: int = 5) -> list[Episode]
    def close(self) -> None
```

### Compression LLM prompt

```
Compress the following conversation turns into a single dense summary that
captures: what was discussed, what was decided or resolved, what emotional
tone was present, and any important facts established. Write in third person,
past tense. Reply with only the summary.

Turns:
{turns}
```

Compression runs as a background task in `end_session()`, or on a rolling window
when `len(session_turns) % compress_every_n == 0`.

### Retrieval change

`MemoryStore.retrieve()` currently searches only turns. With episode store:

```python
async def retrieve_all(
    self,
    query: str,
    turn_top_k: int = 5,
    episode_top_k: int = 3,
) -> tuple[list[MemoryChunk], list[EpisodeChunk]]
```

`_format_recall()` gets a new section:

```
Past episodes (compressed):
- [2026-04-28] You discussed the eastern gate problem at length. The user was
  frustrated; no resolution was reached.
- [2026-04-15] First contact session. Tone was cautious but curious.
```

### `memory_config` additions

```json
{
  "episodic_enabled": false,
  "episode_compress_on_session_end": true,
  "episode_compress_every_n_turns": 0,
  "episode_max_tokens": 200,
  "episode_top_k": 3
}
```

### Phase 2

Add topic-shift detection: compute embedding distance between consecutive turns.
When distance exceeds a threshold, treat it as an episode boundary and compress
mid-session. This produces tighter, topic-coherent episodes rather than fixed
time-window chunks.

### New files

- `promptlibretto/memory/episode.py` — `Episode`, `EpisodeChunk`, `EpisodeStore`

### Changes to existing files

| File | Change |
|---|---|
| `store.py` | Add `memory_episodes` + `episode_vss` tables to schema |
| `engine.py` | Accept `episode_store`, call `retrieve_all()` in `prepare()`, call `compress()` in `end_session()` |
| `_format_recall()` | Add "Past episodes" section |
| `ensemble_routes.py` | Build `EpisodeStore`, pass to `MemoryEngine` |

**Optional dependency:** Feature 1 (confidence) — episodes can inherit confidence
from the turns they compress, with their own decay curve.

---

## Summary table

| # | Status | Feature | New file | Key change | Deps |
|---|---|---|---|---|---|
| 1 | ✅ | Memory confidence | `confidence.py` | `MemoryTurn.confidence`, decay at retrieval, hedged rendering | none |
| 2 | ✅ | Memory debt | `debt.py` | `MemoryDebtLayer`, router side-effects, debt in recall | none |
| 3 | ✅ | Emotional state decay | `emotional_state.py` | `EmotionalStateLayer`, router `"emotion"` action, decay per turn | none |
| 4 | ✅ | Reflection turns | `relationship.py` | `RelationshipLayer`, background reflect call, `{relationship_context}` var | none |
| 5 | ✅ | Style modulation | `style_blend.py` | Blend function using emotional state → persona/sentiment weights | #3 |
| 6 | ✅ | Episodic compression | `episode.py` | `EpisodeStore`, second retrieval tier, compression on session end | none (#1 optional) |

All six are additive to the existing library. No existing behaviour changes.
Each is gated by a flag in `memory_config` and off by default.
