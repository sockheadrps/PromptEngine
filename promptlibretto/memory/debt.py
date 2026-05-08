from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class DebtEntry:
    tag: str
    label: str
    opened_at: str
    session_id: str
    turn_snippet: str = ""


class MemoryDebtLayer:
    """Tracks unresolved conversational threads across sessions.

    Each entry is a topic that was opened by a memory rule and hasn't been
    closed yet. Open debts are prepended to memory_recall so the participant
    always knows what's hanging — no LLM call required.

    Rules open a debt by setting ``opens_debt: true`` and a ``debt_label``.
    Rules close a debt by setting ``closes_debt: "<tag>"``.
    """

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._entries: list[DebtEntry] = []

    def load(self) -> list[DebtEntry]:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                self._entries = [DebtEntry(**e) for e in (raw or [])]
            except Exception:
                self._entries = []
        return self._entries

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(
                [
                    {
                        "tag": e.tag,
                        "label": e.label,
                        "opened_at": e.opened_at,
                        "session_id": e.session_id,
                        "turn_snippet": e.turn_snippet,
                    }
                    for e in self._entries
                ],
                indent=2,
            ),
            encoding="utf-8",
        )

    def open(self, tag: str, label: str, session_id: str, turn_text: str = "") -> None:
        if any(e.tag == tag for e in self._entries):
            return
        self._entries.append(
            DebtEntry(
                tag=tag,
                label=label or tag,
                opened_at=datetime.now(timezone.utc).isoformat(),
                session_id=session_id,
                turn_snippet=(turn_text or "")[:80],
            )
        )

    def close(self, tag: str) -> bool:
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.tag != tag]
        return len(self._entries) < before

    def open_items(self) -> list[DebtEntry]:
        return list(self._entries)

    def clear(self) -> None:
        self._entries = []
        self.save()
