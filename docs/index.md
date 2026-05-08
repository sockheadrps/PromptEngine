# promptlibretto

`promptlibretto` is a schema v2 prompt registry library. It assembles prompts from named sections, runtime state, and an explicit `assembly_order`.

## Minimal Example

```python
from promptlibretto import Engine, MockProvider, Registry

reg = Registry.from_dict({
    "registry": {
        "version": 2,
        "assembly_order": ["output_prompt_directions", "personas.context"],
        "output_prompt_directions": {
            "required": True,
            "items": [{"id": "rules", "text": "Be brief."}],
        },
        "personas": {
            "required": True,
            "items": [{"id": "direct", "context": "Be direct."}],
        },
    }
})

eng = Engine(reg, provider=MockProvider())
print(eng.hydrate({"personas": {"selected": "direct"}}))
```

## Current Public Model

- `Registry`, `Section`, `Route`
- `RegistryState`, `SectionState`
- `ContextItem`, `Persona`, `Sentiment`, `Group`
- `StaticInjection`, `RuntimeInjection`
- `OutputDirection`, `PromptEnding`
- `Display`, `Fragment`, `Scale`

Only schema `version: 2` is supported.

## State Shape

State is keyed by section:

```json
{
  "base_context": {
    "selected": "scene",
    "template_vars": {"place": "the kitchen"}
  },
  "personas": {
    "selected": "direct"
  },
  "sentiment": {
    "selected": "warm",
    "slider": 7,
    "array_modes": {"groups[warm_examples]": "random:1"}
  }
}
```

## Assembly Tokens

- `section`
- `section.field`
- `section.scale`
- `section.groups`
- `section.groups[group_id]`
- `groups[group_id]`
- `injections`

Adjacent blocks from the same section join with one newline. Different sections join with two newlines. Adjacent list blocks can merge when they share a `pre_context`.

## Dynamic Items

Dynamic items may carry:

- `template_vars`
- `template_defaults`
- `fragments`

Fragments use `condition` to render only when a section template variable has a value.

## Groups

Groups are reusable lists of prompt snippets. Attach them to items with `groups: ["group_id"]`, then render with `section.groups` or `section.groups[group_id]`.

## Providers

Use `Engine.hydrate()` for prompt-only rendering, `Engine.run()` for provider generation, and `Engine.stream()` for streaming providers.

Built-ins:

- `MockProvider`
- `OllamaProvider`

## Memory

Install the memory extra and use `MemoryEngine` to add persistent memory on top of any `Engine`:

```bash
pip install "promptlibretto[memory]"
ollama pull nomic-embed-text
```

`MemoryEngine` provides:

- **Semantic retrieval** — embeds user input and retrieves relevant past turns via sqlite-vec
- **Classifier-driven routing** — a small LLM call extracts tags; `memory_rules` map those tags to state mutations
- **Emotional state** — per-participant float vector (warmth, tension, trust, …) that decays toward neutral and shifts via rules
- **Working notes** — background side-call maintains a running per-participant summary updated every N turns
- **System summary** — compresses the assembled system prompt every N model turns
- **Memory debt** — persistent list of unresolved threads opened/closed by rules; injected into recall each turn
- **Episodic compression** — compresses session turns into a single embedded `Episode` on session end; past episodes are retrieved alongside individual turns
- **Relationship arc** — background side-call generates cross-session observations about how the relationship dynamic is changing; injected as `{relationship_context}`

`MemoryEngine.run()` returns the standard `GenerationResult` extended with `retrieved_chunks`, `extracted_tags`, `applied_rules`, and `final_state`.

## Prompt Constructor

```bash
pip install "promptlibretto[prompt-constructor,ollama]"
prompt-constructor --port 8000
```

- **`/`** Studio — runtime tuning surface
- **`/builder`** Builder — visual registry authoring
- **`/chatbuilder`** Chat Builder — conversation-driven registry builder via AI assistant
- **`/ensemble`** Ensemble — two-participant model-vs-model or model-vs-human conversations

## More

- [Design](design.md)
- [Prompt Constructor server notes](server.md)
