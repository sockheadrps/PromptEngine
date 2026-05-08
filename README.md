# promptlibretto

`promptlibretto` is a registry-based prompt construction library. It turns a declarative schema v2 registry into a final prompt string, then can optionally send that prompt to a provider and validate the response.

A registry is made of named sections, selected items, runtime state, and an explicit `assembly_order`.

## Install

```bash
pip install promptlibretto
pip install "promptlibretto[ollama]"
pip install "promptlibretto[dev]"
```

## Quick Start

```python
from promptlibretto import Engine, MockProvider, Registry

reg = Registry.from_dict({
    "registry": {
        "version": 2,
        "title": "Tiny Example",
        "assembly_order": [
            "output_prompt_directions",
            "personas.context",
        ],
        "output_prompt_directions": {
            "required": True,
            "items": [{"id": "rules", "text": "Reply briefly."}],
        },
        "personas": {
            "required": True,
            "items": [
                {"id": "shy", "context": "You are nervous about speaking."},
                {"id": "bold", "context": "You are direct and confident."},
            ],
        },
    }
})

eng = Engine(reg, provider=MockProvider())
print(eng.hydrate({"personas": {"selected": "bold"}}))
```

Output:

```text
Reply briefly.

You are direct and confident.
```

## Schema v2

`Registry.from_dict()` accepts wrapped JSON (`{"registry": {...}}`) or a bare registry dict. The registry must use `version: 2`; older schema versions are rejected.

Core model exports:

- `Registry`, `Section`, `Route`
- `RegistryState`, `SectionState`
- `ContextItem`, `Persona`, `Sentiment`, `Group`
- `StaticInjection`, `RuntimeInjection`
- `OutputDirection`, `PromptEnding`
- `Display`, `Fragment`, `Scale`

There are no compatibility aliases for older schema generations. Use the schema v2 names exported by the package and section-scoped `RegistryState`.

## Runtime State

State is section-scoped:

```python
from promptlibretto import RegistryState, SectionState

state = RegistryState(sections={
    "base_context": SectionState(
        selected="scene",
        template_vars={"place": "the kitchen"},
    ),
    "personas": SectionState(selected="bold"),
    "sentiment": SectionState(
        selected="warm",
        slider=7,                                        # explicit slider value
        slider_random=False,                             # randomise slider within scale range
        section_random=False,                            # randomise which item is selected
        array_modes={"groups[warm_examples]": "random:1"},
    ),
})
```

The equivalent dict form can be passed directly to `hydrate()` / `Engine.run()`:

```python
state = {
    "base_context": {
        "selected": "scene",
        "template_vars": {"place": "the kitchen"},
    },
    "personas": {"selected": "bold"},
    "sentiment": {
        "selected": "warm",
        "slider": 7,
        "array_modes": {"groups[warm_examples]": "random:1"},
    },
}
```

## Assembly Order

`assembly_order` is a list of render tokens:

- `section` renders the selected item's primary field.
- `section.field` renders a named field on the selected item.
- `section.scale` renders the selected item's `Scale`.
- `section.groups` renders groups attached to the selected item.
- `section.groups[group_id]` renders one attached group.
- `groups[group_id]` renders a top-level reusable group.
- `section[item_id]` renders one specific item by ID regardless of selection.
- `section[item_id].field` renders one field of a specific item by ID.
- `injections` renders active runtime injections.

Example:

```json
[
  "output_prompt_directions",
  "base_context.text",
  "personas.context",
  "personas.groups",
  "sentiment.context",
  "sentiment.scale",
  "groups[normal_examples]",
  "prompt_endings"
]
```

## Groups

`Group` is the reusable prompt-snippet container. Attach groups to items with the item's `groups` field, then render them through assembly tokens.

```json
{
  "groups": {
    "required": false,
    "items": [
      {
        "id": "warm_examples",
        "pre_context": "Tone examples:",
        "items": ["That sounds good.", "I'm glad to help."]
      }
    ]
  },
  "sentiment": {
    "required": true,
    "items": [
      {
        "id": "warm",
        "context": "Use a warm tone.",
        "groups": ["warm_examples"]
      }
    ]
  }
}
```

Array modes live in `SectionState.array_modes` and support `all`, `none`, `index:N`, `indices:A,B`, and `random:K`.

## Dynamic Text

Dynamic items can declare `template_vars`, `template_defaults`, and conditional `fragments`.

```json
{
  "id": "scene",
  "text": "You are in {place}.",
  "template_vars": ["place", "weather"],
  "template_defaults": {"place": "the room"},
  "fragments": [
    {
      "id": "weather",
      "condition": "weather",
      "text": "The weather is {weather}."
    }
  ]
}
```

State values win over `template_defaults`. A fragment with `condition` renders only when that section's template variable is non-empty.

## Scale

Any selected item with a `scale` can render through `section.scale`.

```json
{
  "id": "sarcastic",
  "context": "Use dry sarcasm.",
  "scale": {
    "label": "Intensity",
    "scale_descriptor": "sarcasm",
    "min_value": 1,
    "max_value": 10,
    "default_value": 5,
    "template": "{label}: {value}/{max_value} - {scale_descriptor}."
  }
}
```

The rendered value comes from `SectionState.slider`, `SectionState.slider_random`, or the scale's `default_value`.

## Engine

```python
prompt = eng.hydrate(state)
result = await eng.run(state)

async for chunk in eng.stream(state):
    ...
```

`Engine.run()` hydrates the prompt, calls the provider, cleans output, validates it with `OutputPolicy`, and retries up to `generation.retries`.

Built-in providers:

- `MockProvider`
- `OllamaProvider`

## Memory

`MemoryEngine` wraps the core `Engine` with local persistent memory: semantic retrieval, classifier-driven state mutation, emotional state, working notes, and system summaries.

```bash
pip install "promptlibretto[memory]"
ollama pull nomic-embed-text
```

```python
from promptlibretto.memory import MemoryEngine

mem = MemoryEngine(
    engine=eng,
    session_id="user-123",
    embed_url="http://localhost:11434",
    embed_model="nomic-embed-text",
)

prepared = await mem.prepare(user_input, base_state=state)
result = await eng.run(prepared.state)
await mem.record_turn(user_input, role="user")
await mem.record_turn(result.text, role="assistant")
```

Memory is configured in the registry under `memory_config` and `memory_rules`:

```json
{
  "memory_config": {
    "top_k": 6,
    "working_notes_enabled": true,
    "system_summary_enabled": true,
    "emotional_state_enabled": true,
    "emotion_dimensions": ["warmth", "tension", "trust"],
    "emotion_decay_rate": 0.05
  },
  "memory_rules": [
    {
      "tag": "conflict",
      "description": "User is expressing frustration or disagreement.",
      "actions": [{ "type": "emotion", "deltas": { "tension": 0.15, "warmth": -0.1 } }],
      "ending_text": "Acknowledge the friction directly before continuing."
    }
  ]
}
```

`memory_rules` define tags the classifier can match. Each rule can carry `actions` (emotion deltas that shift the participant's emotional state) and an `ending_text` directive injected into the prompt for that turn.

The `memory_recall` section receives retrieved context and working notes via the `{memory_recall}` template variable. `prompt_endings` receives `{system_summary}` and `{rule_ending}`.

See `MEMORY_DESIGN.md` for architecture details and `MEMORY_EXTENSIONS_PLAN.md` for planned extensions.

## Studio

The studio is a browser toolset for building and testing registries.

```bash
pip install "promptlibretto[studio,ollama]"
promptlibretto-studio --port 8000
```

- **Studio** (`/`) — runtime tuning: load a registry, select items, adjust state, preview prompt, generate.
- **Builder** (`/builder`) — visual authoring: build registry JSON from forms and open in Studio.
- **Chat Builder** (`/chatbuilder`) — conversation-driven registry builder: describe what you want and an AI assistant builds the registry through guided tool calls.
- **Ensemble** (`/ensemble`) — two-participant conversation, model-vs-model or model-vs-human, with optional per-participant memory pipeline.

Registry JSON is the shared contract between the library and all four tools. Anything you build in Builder or Chat Builder is immediately usable from Python via `Registry.from_dict()`.

## Development

```bash
pip install "promptlibretto[dev]"
pytest -q
```
