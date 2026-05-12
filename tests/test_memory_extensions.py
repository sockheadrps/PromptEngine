from __future__ import annotations

from types import SimpleNamespace

import pytest

from promptlibretto import RegistryState
from promptlibretto.memory.debt import MemoryDebtLayer
from promptlibretto.memory.engine import _format_recall
from promptlibretto.memory.relationship import RelationshipLayer
from promptlibretto.memory.router import Router
from promptlibretto.memory.store import MemoryChunk, MemoryTurn
from promptlibretto.providers.base import ProviderResponse


def test_router_returns_debt_effects_with_state_mutations() -> None:
    router = Router.from_registry_rules([
        {
            "tag": "conflict",
            "description": "Unresolved friction.",
            "opens_debt": True,
            "debt_label": "Return to the unresolved friction.",
            "actions": [
                {"type": "persona", "value": "careful"},
                {"type": "emotion", "deltas": {"tension": 0.5}},
            ],
            "ending_text": "Acknowledge the friction.",
        },
        {
            "tag": "repair",
            "closes_debt": "conflict",
        },
    ])

    state, deltas, debt_effects = router.mutate(
        RegistryState(),
        ["conflict", "repair"],
    )

    assert state.get("personas").selected == "careful"
    assert deltas == {"tension": 0.12}
    assert debt_effects == [
        {
            "type": "open",
            "tag": "conflict",
            "label": "Return to the unresolved friction.",
        },
        {"type": "close", "tag": "conflict"},
    ]
    assert "Acknowledge the friction." in state._rule_ending_text


def test_memory_debt_layer_persists_and_clears(tmp_path) -> None:
    path = tmp_path / "nested" / "debt.json"
    layer = MemoryDebtLayer(str(path))

    layer.open("conflict", "Follow up on the conflict.", "session-1", "long turn text")
    layer.save()

    loaded = MemoryDebtLayer(str(path))
    assert loaded.load()[0].label == "Follow up on the conflict."
    assert loaded.close("conflict") is True
    loaded.save()
    assert MemoryDebtLayer(str(path)).load() == []

    loaded.open("open", "Open item.", "session-2")
    loaded.clear()
    assert MemoryDebtLayer(str(path)).load() == []


@pytest.mark.asyncio
async def test_relationship_layer_creates_parent_dirs_and_trims(tmp_path) -> None:
    path = tmp_path / "nested" / "relationship.json"

    class Provider:
        async def generate(self, request):
            return ProviderResponse(text="I've noticed we are more direct now.")

    layer = RelationshipLayer(str(path), other_name="Riley")
    layer.load()
    changed = await layer.reflect(
        [
            MemoryTurn(text="Can we be direct?", role="user", session_id="s"),
            MemoryTurn(text="Yes.", role="assistant", session_id="s"),
        ],
        Provider(),
        "mock",
        max_entries=1,
    )

    assert changed is True
    assert path.exists()
    loaded = RelationshipLayer(str(path), other_name="Riley").load()
    assert loaded.entries[-1].text == "I've noticed we are more direct now."
    assert loaded.to_context() == "Relationship arc:\n- I've noticed we are more direct now."


def test_format_recall_includes_new_memory_layers() -> None:
    debt = SimpleNamespace(label="Resolve the billing confusion.")
    episode = SimpleNamespace(summary_text="They previously agreed to review the invoice together.")
    episode_chunk = SimpleNamespace(episode=episode)
    cross_session = MemoryChunk(
        turn=MemoryTurn(
            text="The user prefers concrete next steps.",
            role="user",
            session_id="old-session",
            confidence=0.9,
        ),
        score=0.1,
        confidence=0.9,
    )

    text = _format_recall(
        [],
        [cross_session],
        current_session_id="current-session",
        working_notes="Keep the reply brief.",
        system_summary="System summary text.",
        open_debts=[debt],
        episode_chunks=[episode_chunk],
    )

    assert "Unresolved threads:" in text
    assert "Resolve the billing confusion." in text
    assert "System summary text." in text
    assert "Working notes (your running summary):" in text
    assert "Past episodes:" in text
    assert "They previously agreed" in text
    assert "Relevant past notes:" in text
