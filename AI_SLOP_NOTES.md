# AI Slop Smells — prompt_engine

Honest critique of where the library reads as over-engineered / generated-feeling.
Not a todo list — a reviewer's note to revisit when a second real consumer shows up.

## Abstraction-first, consumers-second

Six layers (`PromptBuilder` Protocol, `CompositeBuilder`, `BuildContext`,
`PromptAssetRegistry`, `PromptInjection`, `Middleware` before/after) with one
real caller (the test bench server). Classic "framework for one app" shape.

## Ceremony for ceremony

`BuildContext` exists so builders "don't need to remember positional args"
([builder.py:42](prompt_engine/builders/builder.py#L42)) — but there are ~two
builders. A function with named params would do the same job.

## Config merge chain sounds principled, caused a real bug

base < route < request. Sounds clean; in practice the UI's Generation Overrides
were silently overridden by route defaults because there was no request-level
layer. The abstraction was incomplete *and* opaque — the worst combination.
(Fix in progress: request-level `config_overrides` applied last.)

## Docstrings hedging against imagined misuse

"Implementations should be small and pure — no I/O, no engine state mutation"
reads as designed-for-reuse that hasn't happened. Nothing enforces it; nothing
would break if it did.

## Feature breadth vs. depth

Streaming + middleware + budget + typed inputs + injections all landed quickly.
Each is ~80% of a real feature; none has a second consumer pressure-testing
the shape. Expect churn once one does.

## What feels earned

- **Provider adapter** — solves a concrete problem (Ollama vs OpenAI payload
  shape divergence, SSE vs newline-JSON streaming).
- **Overlay / snapshot with priority trimming** — real behavior under a real
  constraint (prompt budget).
- **Typed route inputs** — small, opt-in, fails loudly at the boundary.

## If collapsing later

- Inline `BuildContext` into builder call signatures.
- Replace `Middleware` protocol with a list of `(before, after)` callable pairs
  until there's a middleware that actually needs state.
- Delete `PromptAssetRegistry` indirection if injections stay a flat dict.
- Keep `PromptRoute`, `ContextSnapshot`, `ProviderAdapter` — those carry weight.
