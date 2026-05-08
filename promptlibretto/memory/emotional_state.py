"""Emotional state layer — a per-participant float vector that tracks the
current emotional tone of a conversation.

Each dimension lives in [0.0, 1.0] and is pulled toward 0.5 (neutral) by a
configurable decay rate each turn. Memory rules can apply signed deltas to
dimensions when they fire. The formatted state is injected as the
{emotional_state} template variable.

Dimensions are defined in memory_config.emotion_dimensions. Defaults:
  warmth      — 0.5  (cold ↔ warm)
  tension     — 0.5  (calm ↔ tense)
  trust       — 0.5  (suspicious ↔ trusting)
  playfulness — 0.5  (serious ↔ playful)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


DEFAULT_DIMENSIONS = ["warmth", "tension", "trust", "playfulness"]

# Maps dimension value ranges to descriptor words for prompt rendering.
_DESCRIPTORS: dict[str, list[tuple[float, str]]] = {
    "warmth":      [(0.8, "warm"),      (0.6, "somewhat warm"), (0.4, "neutral"), (0.2, "cool"),      (0.0, "cold")],
    "tension":     [(0.8, "very tense"),(0.6, "tense"),         (0.4, "neutral"), (0.2, "relaxed"),   (0.0, "calm")],
    "trust":       [(0.8, "trusting"),  (0.6, "open"),          (0.4, "neutral"), (0.2, "guarded"),   (0.0, "suspicious")],
    "playfulness": [(0.8, "playful"),   (0.6, "light"),         (0.4, "neutral"), (0.2, "measured"),  (0.0, "serious")],
}


def _describe(dimension: str, value: float) -> str:
    scale = _DESCRIPTORS.get(dimension)
    if not scale:
        if value >= 0.7:
            return "high"
        if value >= 0.4:
            return "moderate"
        return "low"
    for threshold, label in scale:
        if value >= threshold:
            return label
    return scale[-1][1]


@dataclass
class EmotionalState:
    dimensions: dict[str, float] = field(default_factory=dict)
    last_updated: str = ""
    turn_count: int = 0

    def decay(self, rate: float = 0.05) -> None:
        """Pull each dimension toward 0.5 (neutral) by `rate` fraction."""
        for k in self.dimensions:
            v = self.dimensions[k]
            self.dimensions[k] = round(v + (0.5 - v) * rate, 4)

    def apply_delta(self, deltas: dict[str, float]) -> None:
        """Apply signed deltas, clamping each dimension to [0.0, 1.0]."""
        for k, d in deltas.items():
            if k in self.dimensions:
                self.dimensions[k] = round(max(0.0, min(1.0, self.dimensions[k] + d)), 4)

    def to_text(self) -> str:
        """Format as a compact natural-language string for prompt injection."""
        if not self.dimensions:
            return ""
        parts = [f"{k}: {_describe(k, v)}" for k, v in self.dimensions.items()]
        return "Emotional tone — " + ", ".join(parts) + "."

    def to_dict(self) -> dict:
        return {
            "dimensions":   self.dimensions,
            "last_updated": self.last_updated,
            "turn_count":   self.turn_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EmotionalState":
        return cls(
            dimensions=dict(d.get("dimensions") or {}),
            last_updated=str(d.get("last_updated") or ""),
            turn_count=int(d.get("turn_count") or 0),
        )


class EmotionalStateLayer:
    """File-backed emotional state for one participant."""

    def __init__(self, path: str, dimensions: list[str]) -> None:
        self._path = path
        self._dimensions = dimensions
        self._state: Optional[EmotionalState] = None

    def load(self) -> EmotionalState:
        if os.path.exists(self._path):
            with open(self._path, encoding="utf-8") as f:
                raw = json.load(f)
            loaded = EmotionalState.from_dict(raw)
            # Add any new dimensions that weren't in the saved file at 0.5.
            for dim in self._dimensions:
                loaded.dimensions.setdefault(dim, 0.5)
            self._state = loaded
        else:
            self._state = EmotionalState(
                dimensions={d: 0.5 for d in self._dimensions}
            )
        return self._state

    @property
    def state(self) -> EmotionalState:
        if self._state is None:
            self.load()
        return self._state  # type: ignore[return-value]

    def save(self) -> None:
        self.state.last_updated = datetime.now(timezone.utc).isoformat()
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self.state.to_dict(), f, indent=2, ensure_ascii=False)

    def clear(self) -> None:
        self._state = EmotionalState(dimensions={d: 0.5 for d in self._dimensions})
        self.save()

    def apply_deltas_and_decay(
        self,
        deltas: dict[str, float],
        decay_rate: float = 0.05,
    ) -> None:
        """Apply rule deltas then decay toward neutral. Call once per turn."""
        if deltas:
            self.state.apply_delta(deltas)
        self.state.decay(decay_rate)
        self.state.turn_count += 1
        self.save()
