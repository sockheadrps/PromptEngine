"""Memory confidence — decay and hedging helpers.

Each stored turn has a base confidence score (1.0 when written). At retrieval
time, confidence is decayed based on how many turns have occurred since then.
When a retrieved chunk's similarity score exceeds a threshold, its stored
confidence is boosted (confirmation signal).

Decayed confidence drives hedged rendering:
  >= 0.75  →  declarative   ("you love jazz")
  >= 0.45  →  soft hedge    ("you seem to enjoy jazz")
  <  0.45  →  uncertain     ("you may have mentioned jazz")
"""
from __future__ import annotations


def decayed_confidence(
    base: float,
    turns_since: int,
    decay_rate: float = 0.02,
    floor: float = 0.1,
) -> float:
    """Compute effective confidence after `turns_since` turns have elapsed."""
    decay = min(turns_since * decay_rate, 0.9)
    return max(floor, base * (1.0 - decay))


def boosted_confidence(
    current: float,
    delta: float = 0.1,
    cap: float = 1.0,
) -> float:
    """Bump confidence when a turn is confirmed by a new retrieval."""
    return min(cap, current + delta)


def hedge(text: str, confidence: float) -> str:
    """Wrap text with an uncertainty qualifier appropriate to the confidence level."""
    if confidence >= 0.75:
        return text
    if confidence >= 0.45:
        return f"(possibly) {text}"
    return f"(uncertain) {text}"
