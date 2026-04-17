from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


@dataclass
class ContextOverlay:
    text: str
    priority: int = 0
    expires_at: Optional[float] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def is_expired(self, now: float) -> bool:
        return self.expires_at is not None and self.expires_at <= now


def make_turn_overlay(
    verbatim: str,
    compacted: Optional[str] = None,
    *,
    priority: int = 25,
    extra_metadata: Optional[Mapping[str, Any]] = None,
) -> ContextOverlay:
    """Build an overlay representing a user iteration turn.

    The active text is the compacted form when present (denser context for
    future turns), otherwise the verbatim text. The verbatim original is
    always preserved in metadata so callers can revert or re-compact later.
    """
    text = compacted if compacted else verbatim
    meta: dict[str, Any] = {"verbatim": verbatim, "kind": "turn"}
    if compacted:
        meta["compacted"] = compacted
    if extra_metadata:
        meta.update(dict(extra_metadata))
    return ContextOverlay(text=text, priority=priority, metadata=meta)


@dataclass
class ContextSnapshot:
    base: str
    active: str
    overlays: dict[str, ContextOverlay] = field(default_factory=dict)
    fields: dict[str, Any] = field(default_factory=dict)
