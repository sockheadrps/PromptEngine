# MCP Registry Sections API

This is a first-pass tool contract for building promptlibretto registries programmatically through MCP calls while matching the Builder's Sections and memory setup flow.

Scope for this draft: registry title/description, assembly order, generation overrides, output policy, the Builder "Yes - configure memory" step, classifier rules, section creation, section-level template vars, section items, fragments, inline groups, list fields, scale settings, style blend, and removal. It does not yet cover validation, import/export, or Studio state.

## Registry Shape

All calls mutate a draft registry object shaped like:

```json
{
  "version": 2,
  "title": "New Registry",
  "description": "",
  "assembly_order": [],
  "generation": {},
  "output_policy": {},
  "memory_rules": [],
  "base_context": { "required": true, "template_vars": [], "items": [] },
  "personas": { "required": true, "template_vars": [], "items": [] },
  "sentiment": { "required": true, "template_vars": [], "items": [] },
  "static_injections": { "required": false, "template_vars": [], "items": [] },
  "runtime_injections": { "required": false, "template_vars": [], "items": [] },
  "output_prompt_directions": { "required": true, "template_vars": [], "items": [] },
  "memory_recall": { "required": false, "template_vars": [], "items": [] },
  "prompt_endings": { "required": true, "template_vars": [], "items": [] }
}
```

Valid `section_key` values:

```text
base_context
personas
sentiment
static_injections
runtime_injections
output_prompt_directions
memory_recall
prompt_endings
```

Template variable names should be stored bare, without braces. Example: store `company`, render/copy as `{company}`.

## Registry Metadata

### `registry.meta.set`

Set Registry Title and Registry Description.

Required params:

```json
{
  "title": "Wizard Tech Prank Caller"
}
```

Optional params:

```json
{
  "description": "A prankster for wizard tech support."
}
```

Effect:

```json
{
  "title": "Wizard Tech Prank Caller",
  "description": "A prankster for wizard tech support."
}
```

## Assembly And Runtime Settings

### `registry.assembly.set_order`

Set the registry assembly order. This controls which prompt parts render, and in what order.

Required params:

```json
{
  "assembly_order": [
    "output_prompt_directions",
    "base_context.text",
    "personas.context",
    "personas.groups",
    "sentiment.context",
    "sentiment.scale",
    "memory_recall.text",
    "prompt_endings.endings"
  ]
}
```

Effect:

```json
{
  "assembly_order": [
    "output_prompt_directions",
    "base_context.text",
    "personas.context",
    "personas.groups",
    "sentiment.context",
    "sentiment.scale",
    "memory_recall.text",
    "prompt_endings.endings"
  ]
}
```

Rules:

- A bare section key renders that section's default text payload.
- A dotted token such as `personas.context` renders one named field.
- `prompt_endings.endings` uses the selected prompt ending item named `endings`.
- Group tokens such as `personas.groups` render attached groups for the selected item.

### `registry.generation.set`

Set generation overrides carried by the registry.

Optional params:

```json
{
  "temperature": 0.85,
  "top_p": 0.65,
  "top_k": 75,
  "max_tokens": 300,
  "repeat_penalty": 1.15,
  "retries": 1
}
```

Effect:

```json
{
  "generation": {
    "temperature": 0.85,
    "top_p": 0.65,
    "top_k": 75,
    "max_tokens": 300,
    "repeat_penalty": 1.15,
    "retries": 1
  }
}
```

Rules:

- Only provided fields need to be written.
- These values are model-call defaults. Studio may override them at runtime.

### `registry.output_policy.set`

Set output policy constraints carried by the registry.

Optional params:

```json
{
  "min_length": 80,
  "max_length": 1000
}
```

Effect:

```json
{
  "output_policy": {
    "min_length": 80,
    "max_length": 1000
  }
}
```

Rules:

- `min_length` and `max_length` are response validation policy, not prompt text.
- Omit the object entirely when no policy is desired.

## Memory Setup

These calls cover the Builder "Yes - configure memory" step and the Memory Config panel.

### `registry.memory.enable`

Apply the default memory-capable structure.

Required params:

```json
{}
```

Effect:

```json
{
  "memory_config": {},
  "memory_recall": {
    "required": false,
    "template_vars": ["memory_recall"],
    "items": [{ "name": "recall", "text": "{memory_recall}" }]
  },
  "prompt_endings": {
    "required": true,
    "template_vars": ["system_summary", "rule_ending"],
    "items": [
      {
        "name": "endings",
        "text": "{system_summary}\n\n{rule_ending}",
        "items": ["you say:"]
      }
    ]
  }
}
```

### `registry.memory.set_classifier`

Set classifier connection and behavior.

Required params:

```json
{
  "classifier_url": "http://localhost:8080",
  "classifier_model": "Qwen3.5-9B-Q4_K_M.gguf"
}
```

Optional params:

```json
{
  "use_classifier": true,
  "auto_inject": false
}
```

Effect:

```json
{
  "memory_config": {
    "use_classifier": true,
    "auto_inject": false,
    "classifier_url": "http://localhost:8080",
    "classifier_model": "Qwen3.5-9B-Q4_K_M.gguf"
  }
}
```

Notes:

- `use_classifier` runs an LLM classifier to extract tags.
- `auto_inject` appends memory recall to the prompt when no `memory_recall` section exists.
- Builder only needs to write `use_classifier: false` when disabled; omitted means enabled.

### `registry.memory.set_embedding`

Set embedding model configuration.

Required params:

```json
{
  "embed_model": "nomic-embed-text:latest"
}
```

Optional params:

```json
{
  "use_separate_embed_url": true,
  "embed_url": "http://localhost:11434"
}
```

Rules:

- If `use_separate_embed_url` is false, omit `embed_url`; runtime falls back to `classifier_url`.
- If `use_separate_embed_url` is true, `embed_url` should be provided.

Effect:

```json
{
  "memory_config": {
    "embed_url": "http://localhost:11434",
    "embed_model": "nomic-embed-text:latest"
  }
}
```

### `registry.memory.set_retrieval`

Set memory retrieval controls.

Required params:

```json
{
  "top_k": 10,
  "prune_keep": 10
}
```

Effect:

```json
{
  "memory_config": {
    "top_k": 10,
    "prune_keep": 10
  }
}
```

Notes:

- `top_k` controls how many memory matches retrieval asks for.
- `prune_keep` controls how many turns to keep when pruning.

### `registry.memory.set_storage`

Set explicit storage paths only when needed.

Optional params:

```json
{
  "store_path": "memory.db",
  "personality_file": "personality.json"
}
```

Rules:

- Usually leave both blank.
- Defaults are workspace + registry scoped by the server.
- Relative paths are anchored inside the registry-specific memory folder.

### `registry.memory.configure`

Convenience call that sets classifier, embedding, retrieval, and storage in one patch.

Required params:

```json
{
  "classifier_url": "http://localhost:8080",
  "classifier_model": "Qwen3.5-9B-Q4_K_M.gguf",
  "embed_model": "nomic-embed-text:latest",
  "top_k": 10,
  "prune_keep": 10
}
```

Optional params:

```json
{
  "use_classifier": true,
  "auto_inject": false,
  "use_separate_embed_url": true,
  "embed_url": "http://localhost:11434",
  "store_path": "",
  "personality_file": ""
}
```

Effect:

```json
{
  "memory_config": {
    "use_classifier": true,
    "auto_inject": false,
    "classifier_url": "http://localhost:8080",
    "classifier_model": "Qwen3.5-9B-Q4_K_M.gguf",
    "embed_url": "http://localhost:11434",
    "embed_model": "nomic-embed-text:latest",
    "top_k": 10,
    "prune_keep": 10
  }
}
```

### `registry.memory.fetch_classifier_models`

Discover classifier models from a local model server.

Required params:

```json
{
  "base_url": "http://localhost:8080"
}
```

Optional params:

```json
{
  "timeout_ms": 5000
}
```

Result:

```json
{
  "ok": true,
  "models": ["Qwen3.5-9B-Q4_K_M.gguf"]
}
```

Discovery behavior should mirror Builder:

- Try `/api/tags`.
- Try `/v1/models`.
- Accept Ollama-style `models[].name`.
- Accept OpenAI-style `data[].id`.

### `registry.memory.fetch_embed_models`

Discover embedding models from the embed server, or classifier server when no separate embed URL is used.

Required params:

```json
{
  "base_url": "http://localhost:11434"
}
```

Optional params:

```json
{
  "timeout_ms": 5000
}
```

Result:

```json
{
  "ok": true,
  "models": ["nomic-embed-text:latest"]
}
```

## Classifier Rules

Classifier rules live in `memory_rules`. The classifier returns tags, and matching tags can inject rule endings or apply actions such as emotional-state deltas.

### `registry.classifier_rule.add`

Add one classifier rule.

Required params:

```json
{
  "rule": {
    "tag": "order_number",
    "description": "When asked about an order number, product ID, or purchase code.",
    "ending_text": "Tell them to hold on, then make up a number confidently."
  }
}
```

Optional rule fields:

```json
{
  "actions": [
    {
      "type": "emotion",
      "deltas": {
        "tension": 0.1,
        "trust": -0.05
      }
    }
  ]
}
```

Effect:

```json
{
  "memory_rules": [
    {
      "tag": "order_number",
      "description": "When asked about an order number, product ID, or purchase code.",
      "ending_text": "Tell them to hold on, then make up a number confidently."
    }
  ]
}
```

Rules:

- `tag` is the classifier output to match.
- `description` tells the classifier when to emit that tag.
- `ending_text` is injected into `{rule_ending}` for the active turn.
- `actions` are optional runtime behaviors, such as emotion deltas.

### `registry.classifier_rule.update`

Update a classifier rule by tag.

Required params:

```json
{
  "tag": "order_number",
  "patch": {
    "description": "When the user asks for any identifying order code.",
    "ending_text": "Delay briefly, then provide a fake code with confidence."
  }
}
```

Allowed patch fields:

```text
tag
description
ending_text
actions
```

### `registry.classifier_rule.remove`

Remove a classifier rule by tag.

Required params:

```json
{
  "tag": "order_number"
}
```

### `registry.classifier_rules.set`

Replace all classifier rules at once.

Required params:

```json
{
  "memory_rules": [
    {
      "tag": "customer_escalating",
      "description": "When the user is angry or threatening escalation.",
      "ending_text": "Stay controlled. Do not match their energy.",
      "actions": [
        {
          "type": "emotion",
          "deltas": {
            "tension": 0.1,
            "trust": -0.05
          }
        }
      ]
    }
  ]
}
```

## Style Blend

Style Blend blends between persona and sentiment items as emotional state shifts. It requires emotional state to be enabled in the ensemble/runtime layer.

### `registry.style_blend.set`

Set Style Blend for `personas` or `sentiment`.

Required params:

```json
{
  "section_key": "personas",
  "axis": "warmth",
  "primary": "calm_persona",
  "secondary": "heated_persona",
  "threshold": 0.6
}
```

Valid `section_key` values:

```text
personas
sentiment
```

Valid Builder axes:

```text
warmth
tension
trust
playfulness
```

Effect:

```json
{
  "style_blend": {
    "personas": {
      "axis": "warmth",
      "primary": "calm_persona",
      "secondary": "heated_persona",
      "threshold": 0.6
    }
  }
}
```

Rules:

- `primary` and `secondary` should reference item IDs in the matching section.
- `threshold` is a number from `0` to `1`.
- Builder defaults threshold to `0.6` if omitted.

### `registry.style_blend.disable`

Remove Style Blend config for a section.

Required params:

```json
{
  "section_key": "sentiment"
}
```

Effect:

```json
{
  "style_blend": {
    "sentiment": null
  }
}
```

## Section Calls

### `registry.sections.ensure`

Create missing standard sections and apply Builder defaults.

Required params:

```json
{}
```

Result:

```json
{
  "ok": true,
  "sections": ["base_context", "personas"]
}
```

### `registry.section.set_required`

Set whether a section is required.

Required params:

```json
{
  "section_key": "base_context",
  "required": true
}
```

### `registry.section.add_var`

Add a section-level template variable, like clicking `+ Add Var`.

Required params:

```json
{
  "section_key": "base_context",
  "name": "working_notes"
}
```

Rules:

- Normalize `{working_notes}` to `working_notes`.
- Do not duplicate existing vars.
- Runtime-injected vars such as `memory_recall`, `system_summary`, and `rule_ending` are still normal vars in the registry.

### `registry.section.remove_var`

Remove a section-level template variable.

Required params:

```json
{
  "section_key": "base_context",
  "name": "working_notes"
}
```

Optional params:

```json
{
  "remove_fragment_conditions": false
}
```

Rules:

- Only remove matching fragment conditions when `remove_fragment_conditions` is true.

### `registry.section.add_item`

Add an item to a section. The item shape depends on section type.

Required params:

```json
{
  "section_key": "personas",
  "item": {
    "id": "old_lady",
    "context": "You are posing as an old lady."
  }
}
```

Minimum item shapes by section:

```json
{
  "base_context": { "id": "context_id", "text": "", "fragments": [] },
  "personas": { "id": "persona_id", "context": "", "groups": [] },
  "sentiment": { "id": "sentiment_id", "context": "", "groups": [], "scale": {} },
  "static_injections": { "id": "injection_id", "text": "", "groups": [] },
  "runtime_injections": { "id": "injection_id", "text": "", "required": false, "template_vars": [] },
  "output_prompt_directions": { "id": "output_id", "text": "" },
  "memory_recall": { "name": "recall", "text": "{memory_recall}" },
  "user_message": { "name": "message", "text": "{user_input}" },
  "prompt_endings": { "name": "endings", "text": "", "items": ["you say:"] }
}
```

### `registry.section.remove_item`

Remove an item by ID/name.

Required params:

```json
{
  "section_key": "personas",
  "item_id": "old_lady"
}
```

Matching rule:

- Match `item.id` first.
- If no `id`, match `item.name`.

## Item Calls

### `registry.item.update`

Update a scalar field on an item.

Required params:

```json
{
  "section_key": "base_context",
  "item_id": "pranker",
  "field": "text",
  "value": "Always-shown text."
}
```

Allowed fields:

```text
id
name
text
context
required
```

Section-specific notes:

- `personas` and `sentiment` use `context`.
- Most text sections use `text`.
- `prompt_endings`, `memory_recall`, and `user_message` use `name` plus `text`.

### `registry.item.add_fragment`

Add a conditional fragment to a `base_context` item.

Required params:

```json
{
  "section_key": "base_context",
  "item_id": "pranker",
  "fragment": {
    "condition": "company",
    "text": "You are calling {company} Support."
  }
}
```

Rules:

- `condition` may be empty for always-rendered fragments.
- Normalize `{company}` to `company`.
- Fragment text may contain `{company}` placeholders.

### `registry.item.update_fragment`

Update a fragment by index.

Required params:

```json
{
  "section_key": "base_context",
  "item_id": "pranker",
  "fragment_index": 0,
  "patch": {
    "condition": "emotional_state",
    "text": "Current emotional state: {emotional_state}."
  }
}
```

Allowed patch fields:

```text
condition
text
```

### `registry.item.remove_fragment`

Remove a fragment by index.

Required params:

```json
{
  "section_key": "base_context",
  "item_id": "pranker",
  "fragment_index": 1
}
```

### `registry.item.add_group`

Attach an inline group to an item.

Required params:

```json
{
  "section_key": "personas",
  "item_id": "my_dad_owns_this_company",
  "group": {
    "id": "when_responding",
    "pre_context": "When responding:",
    "items": ["Bring up that your dad owns the company."]
  }
}
```

Supported sections:

```text
personas
sentiment
static_injections
```

### `registry.item.update_group`

Update an inline group by ID.

Required params:

```json
{
  "section_key": "sentiment",
  "item_id": "core_personality",
  "group_id": "traits",
  "patch": {
    "pre_context": "Core personality traits:"
  }
}
```

Allowed patch fields:

```text
id
pre_context
items
```

### `registry.item.remove_group`

Remove an inline group by ID.

Required params:

```json
{
  "section_key": "sentiment",
  "item_id": "core_personality",
  "group_id": "traits"
}
```

### `registry.group.add_item`

Add one string item to an inline group.

Required params:

```json
{
  "section_key": "sentiment",
  "item_id": "core_personality",
  "group_id": "traits",
  "text": "Confident even when completely wrong."
}
```

### `registry.group.update_item`

Update one string item in an inline group by index.

Required params:

```json
{
  "section_key": "sentiment",
  "item_id": "core_personality",
  "group_id": "traits",
  "item_index": 0,
  "text": "Entitled but weirdly cheerful."
}
```

### `registry.group.remove_item`

Remove one string item from an inline group by index.

Required params:

```json
{
  "section_key": "sentiment",
  "item_id": "core_personality",
  "group_id": "traits",
  "item_index": 0
}
```

### `registry.item.set_scale`

Set or replace a sentiment scale object.

Required params:

```json
{
  "section_key": "sentiment",
  "item_id": "core_personality",
  "scale": {
    "scale_descriptor": "superiority complex",
    "template": "{value}/10 - {scale_descriptor}.",
    "default_value": 5,
    "min_value": 1,
    "max_value": 10
  }
}
```

Supported sections:

```text
sentiment
```

Notes:

- Builder currently exposes scale on sentiment items.
- `scale_descriptor` can be a string or an array of strings for random descriptor selection.

### `registry.item.add_template_var`

Add item-level template vars. Currently this is mainly used by `runtime_injections`.

Required params:

```json
{
  "section_key": "runtime_injections",
  "item_id": "live_lookup",
  "name": "order_status"
}
```

Rules:

- Normalize `{order_status}` to `order_status`.
- Do not duplicate.

### `registry.item.remove_template_var`

Remove item-level template vars.

Required params:

```json
{
  "section_key": "runtime_injections",
  "item_id": "live_lookup",
  "name": "order_status"
}
```

### `registry.item.set_list_field`

Replace a list field such as `prompt_endings.items`.

Required params:

```json
{
  "section_key": "prompt_endings",
  "item_id": "endings",
  "field": "items",
  "items": ["you say:"]
}
```

Allowed fields:

```text
items
```

## Preset Section Bootstraps

These are convenience calls an MCP server could expose on top of the primitives.

### `registry.sections.apply_memory_defaults`

Ensure memory-related template vars exist.

Required params:

```json
{}
```

Effect:

```json
{
  "base_context": ["emotional_state", "working_notes"],
  "memory_recall": ["memory_recall"],
  "prompt_endings": ["system_summary", "rule_ending"]
}
```

### `registry.sections.create_minimal_items`

Create the Builder-style starter items.

Required params:

```json
{}
```

Effect:

```json
{
  "base_context": [{ "id": "base", "text": "", "fragments": [] }],
  "output_prompt_directions": [{ "id": "output", "text": "" }],
  "memory_recall": [{ "name": "recall", "text": "{memory_recall}" }],
  "prompt_endings": [
    {
      "name": "endings",
      "text": "{system_summary}\\n\\n{rule_ending}",
      "items": ["you say:"]
    }
  ]
}
```

## Example Build Sequence

```json
[
  {
    "tool": "registry.meta.set",
    "params": {
      "title": "Wizard Tech Prank Caller",
      "description": "A prankster for wizard tech support."
    }
  },
  { "tool": "registry.sections.ensure", "params": {} },
  {
    "tool": "registry.assembly.set_order",
    "params": {
      "assembly_order": [
        "output_prompt_directions",
        "base_context.text",
        "personas.context",
        "personas.groups",
        "sentiment.context",
        "sentiment.scale",
        "memory_recall.text",
        "prompt_endings.endings"
      ]
    }
  },
  {
    "tool": "registry.generation.set",
    "params": {
      "temperature": 0.85,
      "top_p": 0.65,
      "top_k": 75,
      "max_tokens": 300,
      "repeat_penalty": 1.15,
      "retries": 1
    }
  },
  { "tool": "registry.output_policy.set", "params": { "min_length": 80, "max_length": 1000 } },
  { "tool": "registry.memory.enable", "params": {} },
  {
    "tool": "registry.memory.configure",
    "params": {
      "use_classifier": true,
      "auto_inject": false,
      "classifier_url": "http://localhost:8080",
      "classifier_model": "Qwen3.5-9B-Q4_K_M.gguf",
      "use_separate_embed_url": true,
      "embed_url": "http://localhost:11434",
      "embed_model": "nomic-embed-text:latest",
      "top_k": 10,
      "prune_keep": 10
    }
  },
  {
    "tool": "registry.classifier_rule.add",
    "params": {
      "rule": {
        "tag": "order_number",
        "description": "When asked about an order number, product ID, or purchase code.",
        "ending_text": "Tell them to hold on, then make up a number confidently."
      }
    }
  },
  { "tool": "registry.section.add_var", "params": { "section_key": "base_context", "name": "emotional_state" } },
  { "tool": "registry.section.add_var", "params": { "section_key": "base_context", "name": "working_notes" } },
  { "tool": "registry.section.add_item", "params": { "section_key": "base_context", "item": { "id": "pranker", "text": "", "fragments": [] } } },
  { "tool": "registry.item.add_fragment", "params": { "section_key": "base_context", "item_id": "pranker", "fragment": { "condition": "emotional_state", "text": "Emotional state: {emotional_state}." } } },
  { "tool": "registry.section.add_item", "params": { "section_key": "personas", "item": { "id": "old_lady", "context": "You are posing as an old lady.", "groups": [] } } },
  { "tool": "registry.section.add_item", "params": { "section_key": "sentiment", "item": { "id": "core_personality", "context": "", "groups": [], "scale": { "scale_descriptor": "superiority complex", "template": "{value}/10 - {scale_descriptor}.", "default_value": 5 } } } },
  { "tool": "registry.style_blend.set", "params": { "section_key": "personas", "axis": "warmth", "primary": "old_lady", "secondary": "heated_persona", "threshold": 0.6 } },
  { "tool": "registry.section.add_item", "params": { "section_key": "memory_recall", "item": { "name": "recall", "text": "{memory_recall}" } } },
  { "tool": "registry.section.add_item", "params": { "section_key": "prompt_endings", "item": { "name": "endings", "text": "{system_summary}\\n\\n{rule_ending}", "items": ["you say:"] } } }
]
```

## Open Questions

- Should MCP calls mutate an in-memory draft by `draft_id`, or should every call accept and return the whole registry?
- Should item lookup require exact `item_id`, or should the tool support array indexes for duplicate/blank IDs during early drafting?
- Should section-level `selected`, `array_modes`, and slider state be part of this API, or handled by a separate Studio State API?
- Should inline groups remain embedded on items, or should the MCP layer encourage top-level reusable groups later?
- Should model discovery calls be part of the registry-building MCP server, or a separate connection/model MCP server?
