from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Optional

from ..registry.state import RegistryState, SectionState


@dataclass
class MemoryAction:
    type: str                           # "inject" | "persona" | "sentiment" | "template_var" | "emotion"
    section: Optional[str] = None      # inject: which section; template_var: section owning the var
    item: Optional[str] = None         # inject: item id to activate
    value: Optional[str] = None        # persona / sentiment / template_var: target value
    key: Optional[str] = None          # template_var: variable name
    deltas: dict[str, float] = field(default_factory=dict)  # emotion: dimension deltas

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MemoryAction":
        return cls(
            type=d["type"],
            section=d.get("section"),
            item=d.get("item"),
            value=d.get("value"),
            key=d.get("key"),
            deltas=dict(d.get("deltas") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.type}
        if self.section is not None:
            out["section"] = self.section
        if self.item is not None:
            out["item"] = self.item
        if self.value is not None:
            out["value"] = self.value
        if self.key is not None:
            out["key"] = self.key
        if self.deltas:
            out["deltas"] = self.deltas
        return out


@dataclass
class MemoryRule:
    tag: str
    actions: list[MemoryAction] = field(default_factory=list)
    description: str = ""
    ending_text: str = ""  # injected into prompt_endings as {rule_ending} when this rule fires

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MemoryRule":
        return cls(
            tag=d["tag"],
            actions=[MemoryAction.from_dict(a) for a in (d.get("actions") or [])],
            description=str(d.get("description") or ""),
            ending_text=str(d.get("ending_text") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"tag": self.tag, "actions": [a.to_dict() for a in self.actions]}
        if self.description:
            out["description"] = self.description
        if self.ending_text:
            out["ending_text"] = self.ending_text
        return out


class Router:
    """Maps extracted memory tags to RegistryState mutations.

    Rules are evaluated in order; last rule wins on conflicts for the same
    field. Injection activations are additive.
    """

    def __init__(self, rules: list[MemoryRule]) -> None:
        self._rules = rules
        self._known_tags: list[str] = [r.tag for r in rules]

    @property
    def known_tags(self) -> list[str]:
        return list(self._known_tags)

    @property
    def tag_descriptions(self) -> dict[str, str]:
        return {r.tag: r.description for r in self._rules if r.description}

    def mutate(
        self,
        base_state: RegistryState,
        tags: list[str],
    ) -> tuple[RegistryState, dict[str, float]]:
        """Mutate registry state based on matched tags.

        Returns (mutated_state, emotion_deltas). emotion_deltas is a dict of
        {dimension: delta} aggregated across all fired rules — callers apply
        these to EmotionalStateLayer after mutate() returns.
        """
        if not tags:
            return base_state, {}

        tag_set = set(tags)
        active_rules = [r for r in self._rules if r.tag in tag_set]
        if not active_rules:
            return base_state, {}

        # Deep-copy all existing section states
        new_sections: dict[str, SectionState] = {
            k: SectionState(
                selected=list(v.selected) if isinstance(v.selected, list) else v.selected,
                slider=v.slider,
                slider_random=v.slider_random,
                section_random=v.section_random,
                array_modes=dict(v.array_modes),
                template_vars=dict(v.template_vars),
            )
            for k, v in base_state.sections.items()
        }

        def _sec(sec_id: str) -> SectionState:
            if sec_id not in new_sections:
                new_sections[sec_id] = SectionState()
            return new_sections[sec_id]

        applied: list[str] = []
        emotion_deltas: dict[str, float] = {}

        for rule in active_rules:
            for action in rule.actions:

                if action.type == "inject" and action.section and action.item:
                    ss = _sec(action.section)
                    existing = ss.selected
                    if isinstance(existing, list):
                        if action.item not in existing:
                            existing.append(action.item)
                    elif isinstance(existing, str):
                        if existing != action.item:
                            ss.selected = [existing, action.item]
                    else:
                        ss.selected = action.item
                    applied.append(f"{rule.tag} → inject:{action.section}.{action.item}")

                elif action.type == "persona" and action.value:
                    _sec("personas").selected = action.value
                    applied.append(f"{rule.tag} → persona:{action.value}")

                elif action.type == "sentiment" and action.value:
                    _sec("sentiment").selected = action.value
                    applied.append(f"{rule.tag} → sentiment:{action.value}")

                elif action.type == "template_var" and action.key and action.value:
                    sec_id = action.section or "base_context"
                    var = action.key
                    _sec(sec_id).template_vars[var] = action.value
                    applied.append(f"{rule.tag} → tvar:{sec_id}.{var}={action.value}")

                elif action.type == "emotion" and action.deltas:
                    for dim, delta in action.deltas.items():
                        emotion_deltas[dim] = emotion_deltas.get(dim, 0.0) + delta
                    delta_str = ", ".join(f"{k}{v:+.2f}" for k, v in action.deltas.items())
                    applied.append(f"{rule.tag} → emotion:{delta_str}")

        # Cap per-turn aggregate deltas so multiple rules firing simultaneously
        # can't slam a dimension to the ceiling in a single turn.
        _MAX = 0.12
        emotion_deltas = {k: max(-_MAX, min(_MAX, v)) for k, v in emotion_deltas.items()}

        ending_texts = [r.ending_text for r in active_rules if r.ending_text]

        new_state = RegistryState(sections=new_sections)
        new_state._applied_rules = applied  # type: ignore[attr-defined]
        new_state._rule_ending_text = "\n\n".join(ending_texts)  # type: ignore[attr-defined]
        return new_state, emotion_deltas

    @classmethod
    def from_registry_rules(cls, rules_raw: list[dict[str, Any]]) -> "Router":
        return cls([MemoryRule.from_dict(r) for r in (rules_raw or [])])
