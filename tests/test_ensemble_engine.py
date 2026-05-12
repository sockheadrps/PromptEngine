from __future__ import annotations

from prompt_constructor.ensemble.engine import EnsembleEngine, Participant, Turn


class _Engine:
    def hydrate(self, _state, seed=None):
        return "system prompt"

    def _cfg_policy_for(self, _route):
        raise AssertionError("not used")


def test_messages_start_with_user_when_speaker_has_opening_turn():
    speaker = Participant(name="A", engine=_Engine(), model="m")
    other = Participant(name="B", engine=_Engine(), model="m")
    ensemble = EnsembleEngine(speaker, other)
    ensemble.history = [
        Turn(speaker="A", text="A opens."),
        Turn(speaker="B", text="B replies."),
    ]

    messages = ensemble._build_messages_from_state(
        speaker,
        None,
        scene_context="shared scene",
        other_name="B",
    )

    assert [m.role for m in messages] == ["system", "user", "assistant", "user"]
    assert "Continue the conversation" in messages[1].content
    assert messages[2].content == "A opens."
    assert messages[3].content == "B replies."
