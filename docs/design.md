# Design

`promptlibretto` schema v2 is built around a small set of concepts:

- A `Registry` is the prompt blueprint.
- A `Section` owns authored items.
- `RegistryState` / `SectionState` own runtime choices.
- `assembly_order` owns render order.
- `Group` owns reusable prompt snippets.
- `Scale` owns slider-driven prompt text.

Only schema `version: 2` is supported.

## Registry and Sections

Sections are blueprint containers:

```python
Section(id="personas", required=True, items=[...])
```

Runtime data is separate:

```python
RegistryState(sections={
    "personas": SectionState(selected="direct")
})
```

Canonical sections:

- `base_context`
- `personas`
- `sentiment`
- `static_injections`
- `runtime_injections`
- `output_prompt_directions`
- `groups`
- `prompt_endings`

## Tokens

`assembly_order` supports:

- `section` — selected item's primary field
- `section.field` — named field on the selected item
- `section.scale` — selected item's Scale
- `section.groups` — all groups attached to the selected item
- `section.groups[group_id]` — one attached group
- `groups[group_id]` — top-level reusable group
- `section[item_id]` — one specific item by ID regardless of selection
- `section[item_id].field` — one field of a specific item by ID
- `injections` — active runtime injections

Same-section blocks join with one newline. Different sections join with two newlines.

## Groups

Groups are reusable snippet lists:

```json
{
  "id": "brief_examples",
  "pre_context": "Examples:",
  "items": ["Got it.", "Checking now."]
}
```

Attach with:

```json
{
  "id": "support_agent",
  "context": "You are concise.",
  "groups": ["brief_examples"]
}
```

Render with `personas.groups` or `personas.groups[brief_examples]`.

## Dynamic Items

Dynamic items can define `template_vars`, `template_defaults`, and `fragments`.

Fragments use `condition`:

```json
{
  "id": "detail",
  "condition": "ticket_id",
  "text": "Ticket: {ticket_id}."
}
```

The fragment renders only when that section's `ticket_id` value is present.

## Scale

`section.scale` renders the selected item's `Scale`. The value comes from `SectionState.slider`, randomization, or `default_value`.

## Injections

`runtime_injections` render through `injections`. If injections are selected but the token is not present, they append to the end.

`include_sections` is item metadata in v2; it does not filter the assembled prompt.

## Routes

Routes are optional named overrides:

```python
Route(
    assembly_order=[...],
    generation={"max_tokens": 64},
    output_policy={"max_length": 240},
    default_state=RegistryState(...),
)
```

With no route active, the top-level registry assembly order and config are used.

## Memory

Registries may include `memory_rules` and `memory_config` to enable the memory layer.

`memory_rules` maps tags to `RegistryState` mutations (inject, persona, sentiment, template_var actions), emotion deltas, and debt side-effects (`opens_debt` / `closes_debt`). The classifier extracts matching tags from user input and retrieved past turns; the router applies mutations before hydration.

`memory_config` keys:

| Key | Purpose |
|---|---|
| `top_k` | Number of past turns to retrieve per query |
| `history_window` | Recent turns to include verbatim in recall |
| `embed_model` | Ollama embedding model (default `nomic-embed-text`) |
| `classifier_model` | Tag-extraction model (default `llama3.2:1b`) |
| `working_notes_enabled` | Background running-notes side-call |
| `system_summary_enabled` | Background system-prompt compression |
| `emotional_state_enabled` | Per-participant emotion vector |
| `emotion_dimensions` | Dimension names (default `["warmth","tension","trust","playfulness"]`) |
| `emotion_decay_rate` | Pull-toward-neutral rate per turn (default `0.05`) |
| `debt_enabled` | Persistent unresolved-thread tracking |
| `episodic_enabled` | Compressed session-level episode store |
| `relationship_enabled` | Cross-session relationship arc reflections |
| `relationship_reflect_every_n_turns` | How often to generate a reflection (default `10`) |
| `auto_inject` | Append recall to system prompt when no section declares `{memory_recall}` |

Template variables injected by `MemoryEngine.prepare()`:

- `{memory_recall}` — combined block: debt threads, system summary, working notes, past episodes, recent conversation, retrieved cross-session chunks
- `{emotional_state}` — current emotion vector as human-readable text
- `{relationship_context}` — accumulated relationship arc observations
- `{working_notes}`, `{system_summary}`, `{rule_ending}`, `{user_input}`, `{other_name}`, `{thoughts_about_other}`

See `MEMORY_DESIGN.md` for the full architecture.
