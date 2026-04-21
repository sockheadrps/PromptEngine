from __future__ import annotations

from promptlibretto import (
    ContextOverlay,
    PromptEngine,
    export_python,
    section,
)


def _exec(code: str) -> dict:
    ns: dict = {}
    exec(code, ns)
    return ns


async def test_export_produces_runnable_code():
    engine = PromptEngine(routes={"default": "Say hi."})
    code = export_python(engine)
    ns = _exec(code)
    assert "engine" in ns
    result = await ns["engine"].generate_once()
    assert "Say hi." in result.text


async def test_export_preserves_system_and_user_sections():
    engine = PromptEngine(routes={
        "r": {
            "system_sections": ["You are terse."],
            "user_sections": ["Q"],
        }
    })
    code = export_python(engine, route="r")
    assert "You are terse." in code
    ns = _exec(code)
    result = await ns["engine"].generate_once()
    assert "Q" in result.text


async def test_export_input_slot_becomes_lambda():
    engine = PromptEngine(routes={
        "r": {
            "user_sections": [
                section(lambda ctx: f"Q:\n{ctx.request.inputs.get('input', '')}"),
            ],
        }
    })
    code = export_python(engine, route="r")
    assert "lambda ctx" in code
    ns = _exec(code)
    result = await ns["engine"].generate_once("hello there")
    assert "Q:\nhello there" in result.text


async def test_export_preserves_overlays():
    engine = PromptEngine(
        context_store="BASE",
        routes={"default": "Q"},
    )
    engine.context_store.set_overlay(
        "note", ContextOverlay(text="Use markdown.", priority=15)
    )
    code = export_python(engine)
    assert "set_overlay" in code
    assert "Use markdown." in code
    ns = _exec(code)
    state = ns["engine"].context_store.get_state()
    assert "note" in state.overlays
    assert state.overlays["note"].priority == 15


async def test_export_preserves_generation_overrides():
    engine = PromptEngine(routes={
        "r": {"user_sections": ["Q"], "generation_overrides": {"temperature": 0.33}}
    })
    code = export_python(engine, route="r")
    ns = _exec(code)
    route = ns["engine"].router.get("r")
    assert route.builder.generation_overrides["temperature"] == 0.33


async def test_export_preserves_base_context():
    engine = PromptEngine(context_store="SYSTEM BASE", routes={"default": "Q"})
    code = export_python(engine)
    ns = _exec(code)
    assert ns["engine"].context_store.get_state().base == "SYSTEM BASE"


async def test_export_emits_run_wrapper_with_runtime_slots():
    import pytest
    engine = PromptEngine(context_store="BASE", routes={"default": "Q"})
    engine.context_store.set_overlay(
        "location",
        ContextOverlay(text="placeholder", priority=20, metadata={"runtime": "required"}),
    )
    engine.context_store.set_overlay(
        "focus",
        ContextOverlay(text="placeholder", priority=15, metadata={"runtime": "optional"}),
    )
    engine.context_store.set_overlay(
        "fixed_note", ContextOverlay(text="Use markdown.", priority=10),
    )
    code = export_python(engine)

    # Fixed overlays still emitted; runtime ones moved into run() body.
    assert "Use markdown." in code
    assert "async def run(" in code
    assert "location: str" in code
    assert "focus: str = \"\"" in code
    assert "**extra: str" in code

    ns = _exec(code)
    assert "run" in ns

    # Required missing → ValueError.
    with pytest.raises(ValueError):
        await ns["run"]("hi", location="")

    # Required provided → overlay set, optional left absent.
    await ns["run"]("hello", location="kitchen")
    state = ns["engine"].context_store.get_state()
    assert state.overlays["location"].text == "kitchen"
    assert state.overlays["location"].priority == 20

    # Extra kwargs become priority-10 overlays.
    await ns["run"]("hello", location="kitchen", scenario_focus="cooking")
    state = ns["engine"].context_store.get_state()
    assert state.overlays["scenario_focus"].text == "cooking"
    assert state.overlays["scenario_focus"].priority == 10

    # Fixed overlay survives runtime reset.
    assert "fixed_note" in state.overlays
    assert state.overlays["fixed_note"].text == "Use markdown."

    # A second call WITHOUT scenario_focus must clear it.
    await ns["run"]("again", location="kitchen")
    state = ns["engine"].context_store.get_state()
    assert "scenario_focus" not in state.overlays
    assert "fixed_note" in state.overlays  # fixed still there


async def test_runtime_overlay_skipped_in_active_context():
    from promptlibretto import ContextStore
    store = ContextStore(base="BASE")
    store.set_overlay(
        "loc", ContextOverlay(text="placeholder", priority=20, metadata={"runtime": "required"}),
    )
    store.set_overlay("fact", ContextOverlay(text="fixed fact", priority=10))
    snap = store.get_state()
    # Both overlays are visible in the snapshot...
    assert {"loc", "fact"} <= set(snap.overlays)
    # ...but the runtime placeholder is NOT in the rendered active text.
    assert "placeholder" not in snap.active
    assert "fixed fact" in snap.active
