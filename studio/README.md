# promptlibretto studio

Browser-based prompt designer for the `promptlibretto` library. Load a
registry, tune selections and runtime modes against a live local model,
and export the final JSON to drop into your app.

Full docs: **[sockheadrps.github.io/promptlibretto/server](https://sockheadrps.github.io/promptlibretto/server/)**

## Run it

```bash
pip install "promptlibretto[studio,ollama]"
promptlibretto-studio --port 8000
```

Open <http://localhost:8000>.

## Pages

### Studio (`/`)

The main tuning surface. Load a registry via **Import JSON…** (paste
JSON) or receive one from the Builder. Each registry section renders
as a card with:

- A selection control (dropdown for required sections, checkboxes for
  optional ones).
- A **Random at run time** toggle — re-rolls the selection on every
  Pre-generate / Generate.
- An **inline editor** pre-filled with the selected item's fields —
  edits write back to the in-memory registry.
- **Template var** inputs for each declared `{variable}`.

Sections split across two tabs:

- **Compose** — Base Context, Personas, Sentiment (with its intensity
  slider), Static / Runtime Injections.
- **Tuning** — Generation Overrides (temperature, top_p, top_k,
  max_tokens, repeat_penalty, retries, max_prompt_chars), Examples,
  Prompt Endings. Browser-direct generation uses the sampling fields;
  `retries` is used by `Engine.run()` and `/api/registry/generate`.
  `max_prompt_chars` is currently stored/exported but not enforced by
  the engine.

![Studio Compose view](../docs/assets/screenshots/studio-compose.png)

![Studio Tuning view](../docs/assets/screenshots/studio-tuning.png)

Hit **Pre-generate** to see the assembled prompt, then **Generate** to
send it browser-direct to your local Ollama. Browser-direct generation
uses the server for hydration but does not apply Python-side output
policy validation or retries. The stream toggle streams tokens as they
arrive. **Export Model JSON** copies the full
registry — selections, modes, sliders, and generation overrides baked
in — ready for `load_registry()` in your app.

![Pre-generate review](../docs/assets/screenshots/studio-pregenerate.png)

![Generated output](../docs/assets/screenshots/studio-output.png)

### Builder (`/builder`)

Visual form for constructing a new registry from scratch.

- **Load Example** — fills every section with a complete example.
- **Import JSON** — load an existing registry into the form.
- Sections, Assembly Order, and Generation / Policy tabs mirror the
  registry schema.
- **Validate** — schema-checks the current JSON against the server.
- **Generate Registry** — copies / downloads the finished JSON.
- **Open in Studio** — sends the registry to the Studio tab via
  `localStorage`.

![Builder overview](../docs/assets/screenshots/builder-overview.png)

## Connection

The studio calls your local LLM directly from the browser after using
the backend to hydrate the prompt. Click the connection chip in the
header to set the base URL, chat path, payload shape (Ollama /
OpenAI-compatible), and model. Settings persist in `localStorage`.

![Connection settings](../docs/assets/screenshots/connection-modal.png)

## Snapshots

**Snapshots** (header button) saves / restores full panel state:
registry, selections, modes, sliders, template vars, generation
overrides. Storage is `localStorage`; snapshots persist across
reloads but stay on the device.

![Snapshots modal](../docs/assets/screenshots/snapshots-modal.png)

## Registry HTTP API

The studio also exposes these endpoints for headless use:

| Endpoint                      | Purpose                                   |
| ----------------------------- | ----------------------------------------- |
| `POST /api/registry/load`     | Parse and canonicalize a registry JSON.   |
| `POST /api/registry/hydrate`  | Assemble the prompt for a registry + state. |
| `POST /api/registry/generate` | Hydrate + LLM + Python output policy.     |
| `GET  /health`                | Liveness check.                           |

Server-side generation uses `OllamaProvider`. Set
`PROMPT_ENGINE_MOCK=1` to use `MockProvider`, or `OLLAMA_URL` /
`OLLAMA_CHAT_PATH` to point at a different host.

## Files

- [`main.py`](main.py) — FastAPI app, lifespan, API endpoints.
- [`static/indexv2.html`](static/indexv2.html) — Studio page.
- [`static/appv2.js`](static/appv2.js) — Studio logic.
- [`static/stylev2.css`](static/stylev2.css) — Studio styles.
- [`static/templatebuilder.html`](static/templatebuilder.html) — Builder page.
- [`static/templatebuilder.js`](static/templatebuilder.js) — Builder logic.
- [`static/templatebuilder.css`](static/templatebuilder.css) — Builder styles.
- [`static/connection.js`](static/connection.js) — Connection modal + chip.
- [`static/ollama_client.js`](static/ollama_client.js) — Browser-side Ollama / OpenAI-compat client.
- [`static/session.js`](static/session.js) — Workspace chip.
- [`static/examples/`](static/examples/) — Studio example registries.
- [`static/builder-examples/`](static/builder-examples/) — Builder example registries.
- Snapshots are stored in browser `localStorage` under
  `pl-registry-snapshots-v1`.
