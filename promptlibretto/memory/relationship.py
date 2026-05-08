from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..providers.base import ProviderAdapter
    from .store import MemoryTurn


_REFLECT_PROMPT = """\
You are reviewing a conversation to identify how the relationship between \
{self_name} and {other_name} has changed.

{persona_block}\
Recent conversation:
{turns}

Existing relationship observations:
{existing}

Write a single sentence describing a meaningful change in the relationship \
dynamic — something new that isn't already captured above. Write in first \
person from {self_name}'s perspective, past tense. Begin with "I've noticed" \
or "I'm starting to" or "It feels like". If nothing meaningful has changed, \
reply with the exact text: nothing new"""


@dataclass
class ReflectionEntry:
    text: str
    timestamp: str
    session_id: str
    turn_count_at: int
    valence: str = "neutral"  # "positive" | "negative" | "neutral"


@dataclass
class RelationshipProfile:
    other_name: str
    entries: list[ReflectionEntry] = field(default_factory=list)
    last_reflected_at: str = ""
    reflect_count: int = 0

    def to_context(self, max_entries: int = 5) -> str:
        if not self.entries:
            return ""
        recent = self.entries[-max_entries:]
        lines = [f"- {e.text}" for e in recent]
        return "Relationship arc:\n" + "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "other_name":        self.other_name,
            "entries":           [_entry_to_dict(e) for e in self.entries],
            "last_reflected_at": self.last_reflected_at,
            "reflect_count":     self.reflect_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RelationshipProfile":
        return cls(
            other_name=d.get("other_name", ""),
            entries=[_entry_from_dict(e) for e in (d.get("entries") or [])],
            last_reflected_at=d.get("last_reflected_at", ""),
            reflect_count=int(d.get("reflect_count", 0)),
        )


def _entry_to_dict(e: ReflectionEntry) -> dict:
    return {
        "text":          e.text,
        "timestamp":     e.timestamp,
        "session_id":    e.session_id,
        "turn_count_at": e.turn_count_at,
        "valence":       e.valence,
    }


def _entry_from_dict(d: dict) -> ReflectionEntry:
    return ReflectionEntry(
        text=d.get("text", ""),
        timestamp=d.get("timestamp", ""),
        session_id=d.get("session_id", ""),
        turn_count_at=int(d.get("turn_count_at", 0)),
        valence=d.get("valence", "neutral"),
    )


class RelationshipLayer:
    """Persistent cross-session observations about the relationship dynamic."""

    def __init__(self, path: str, other_name: str = "") -> None:
        self._path = path
        self._other_name = other_name
        self._profile: RelationshipProfile = RelationshipProfile(other_name=other_name)

    def load(self) -> RelationshipProfile:
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            self._profile = RelationshipProfile.from_dict(data)
        except (FileNotFoundError, json.JSONDecodeError):
            self._profile = RelationshipProfile(other_name=self._other_name)
        return self._profile

    @property
    def profile(self) -> RelationshipProfile:
        return self._profile

    def save(self) -> None:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._profile.to_dict(), f, indent=2)

    def clear(self) -> None:
        self._profile = RelationshipProfile(other_name=self._other_name)
        self.save()

    async def reflect(
        self,
        recent_turns: "list[MemoryTurn]",
        provider: "ProviderAdapter",
        model: str,
        *,
        persona: Optional[str] = None,
        self_name: str = "you",
        other_name: Optional[str] = None,
        max_tokens: int = 150,
        max_entries: int = 20,
    ) -> bool:
        """Run an LLM side-call to generate a new relationship observation.

        Returns True if a new entry was appended, False otherwise.
        """
        if not recent_turns:
            return False

        resolved_other = other_name or self._other_name or "them"
        turns_text = "\n".join(
            f"{'User' if t.role == 'user' else self_name}: {(t.text or '').strip()[:300]}"
            for t in recent_turns[-20:]
        )
        existing_text = self._profile.to_context(max_entries=max_entries) or "None yet."
        persona_block = f"{persona.strip()}\n\n" if persona and persona.strip() else ""

        prompt = _REFLECT_PROMPT.format(
            self_name=self_name,
            other_name=resolved_other,
            persona_block=persona_block,
            turns=turns_text,
            existing=existing_text,
        )

        try:
            from ..providers.base import ProviderMessage, ProviderRequest
            request = ProviderRequest(
                model=model,
                messages=[ProviderMessage(role="user", content=prompt)],
                max_tokens=max_tokens,
                temperature=0.5,
            )
            response = await provider.generate(request)
            text = (response.text or "").strip()
        except Exception:
            return False

        if not text or text.lower().startswith("nothing new"):
            return False

        valence = _guess_valence(text)
        entry = ReflectionEntry(
            text=text,
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id="",
            turn_count_at=len(recent_turns),
            valence=valence,
        )
        self._profile.entries.append(entry)
        self._profile.last_reflected_at = entry.timestamp
        self._profile.reflect_count += 1

        # Trim to max_entries.
        if len(self._profile.entries) > max_entries:
            self._profile.entries = self._profile.entries[-max_entries:]

        self.save()
        return True


def _guess_valence(text: str) -> str:
    lower = text.lower()
    positive_words = {"open", "trust", "closer", "warm", "relax", "comfortable", "genuine", "honest", "kind"}
    negative_words = {"distant", "guard", "tension", "frustrat", "withdraw", "cold", "hostile", "disappoint"}
    pos = sum(1 for w in positive_words if w in lower)
    neg = sum(1 for w in negative_words if w in lower)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"
