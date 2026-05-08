from __future__ import annotations

import json
import sqlite3
import struct
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .embedder import OllamaEmbedder
    from .store import MemoryTurn


@dataclass
class Episode:
    id: str
    session_id: str
    summary_text: str
    timestamp: str
    tags: list[str] = field(default_factory=list)
    confidence: float = 1.0
    turn_count: int = 0
    start_turn_index: int = 0
    end_turn_index: int = 0


@dataclass
class EpisodeChunk:
    episode: Episode
    score: float


_COMPRESS_PROMPT = """\
Compress the following conversation turns into a single dense summary.
Capture: what was discussed, what was decided or resolved, the emotional tone, \
and any important facts established.
Write in third person, past tense. Reply with only the summary — no preamble, \
no label, no explanation.

Turns:
{turns}"""


def _pack(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


class EpisodeStore:
    """Compressed episode storage alongside the turn store.

    Uses the same .db file as MemoryStore (adds its own tables on init).
    Compression is a side-call: ``compress()`` takes a provider + model and
    runs as a background task — never blocks the main generation path.
    """

    def __init__(
        self,
        db_path: str,
        embedder: "OllamaEmbedder",
        dimensions: int = 768,
    ) -> None:
        self._path = db_path
        self.embedder = embedder
        self.dimensions = dimensions
        self._db = self._connect()

    def _connect(self) -> sqlite3.Connection:
        try:
            import sqlite_vec
        except ImportError as e:
            raise ImportError(
                "sqlite-vec is required for episodic memory. "
                "Install it with: pip install 'promptlibretto[memory]'"
            ) from e

        db = sqlite3.connect(self._path)
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
        db.row_factory = sqlite3.Row

        db.executescript(f"""
            CREATE TABLE IF NOT EXISTS memory_episodes (
                id                TEXT PRIMARY KEY,
                session_id        TEXT NOT NULL DEFAULT '',
                summary_text      TEXT NOT NULL,
                tags              TEXT NOT NULL DEFAULT '[]',
                timestamp         TEXT NOT NULL,
                confidence        REAL NOT NULL DEFAULT 1.0,
                turn_count        INTEGER NOT NULL DEFAULT 0,
                start_turn_index  INTEGER NOT NULL DEFAULT 0,
                end_turn_index    INTEGER NOT NULL DEFAULT 0
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS episode_vss USING vec0(
                episode_id  TEXT,
                embedding   float[{self.dimensions}]
            );
        """)
        db.commit()
        return db

    async def compress(
        self,
        turns: "list[MemoryTurn]",
        provider: object,
        model: str,
        *,
        session_id: str = "",
        max_tokens: int = 200,
    ) -> Optional[Episode]:
        """Summarise turns into an Episode, embed it, and store it.

        Skips silently if the session is already compressed or turns is empty.
        Returns the new Episode, or None on failure / skip.
        """
        if not turns:
            return None

        # Don't compress the same session twice.
        if session_id and self._session_compressed(session_id):
            return None

        turns_text = "\n".join(
            f"{'User' if t.role == 'user' else 'Agent'}: {(t.text or '').strip()[:300]}"
            for t in turns
        )
        prompt = _COMPRESS_PROMPT.format(turns=turns_text)

        try:
            from ..providers.base import ProviderMessage, ProviderRequest
            request = ProviderRequest(
                model=model,
                messages=[ProviderMessage(role="user", content=prompt)],
                max_tokens=max_tokens,
                temperature=0.3,
            )
            response = await provider.generate(request)
            summary = (response.text or "").strip()
        except Exception:
            return None

        if not summary:
            return None

        try:
            vector = await self.embedder.embed(summary)
        except Exception:
            return None

        episode = Episode(
            id=str(uuid.uuid4()),
            session_id=session_id,
            summary_text=summary,
            timestamp=datetime.now(timezone.utc).isoformat(),
            tags=list({tag for t in turns for tag in (t.tags or [])}),
            confidence=1.0,
            turn_count=len(turns),
            start_turn_index=0,
            end_turn_index=len(turns) - 1,
        )

        self._db.execute(
            """
            INSERT OR REPLACE INTO memory_episodes
                (id, session_id, summary_text, tags, timestamp, confidence,
                 turn_count, start_turn_index, end_turn_index)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                episode.id,
                episode.session_id,
                episode.summary_text,
                json.dumps(episode.tags),
                episode.timestamp,
                episode.confidence,
                episode.turn_count,
                episode.start_turn_index,
                episode.end_turn_index,
            ),
        )
        self._db.execute(
            "INSERT OR REPLACE INTO episode_vss (episode_id, embedding) VALUES (?, ?)",
            (episode.id, _pack(vector)),
        )
        self._db.commit()
        return episode

    async def retrieve(self, query: str, top_k: int = 3) -> list[EpisodeChunk]:
        if top_k <= 0 or not query.strip():
            return []
        try:
            vector = await self.embedder.embed(query)
        except Exception:
            return []

        rows = self._db.execute(
            """
            SELECT v.episode_id, v.distance
            FROM episode_vss v
            WHERE v.embedding MATCH ?
              AND k = ?
            ORDER BY v.distance
            """,
            (_pack(vector), top_k),
        ).fetchall()

        chunks: list[EpisodeChunk] = []
        for row in rows:
            ep_row = self._db.execute(
                "SELECT * FROM memory_episodes WHERE id = ?", (row["episode_id"],)
            ).fetchone()
            if not ep_row:
                continue
            chunks.append(EpisodeChunk(episode=_row_to_episode(ep_row), score=row["distance"]))
        return chunks

    def recent(self, limit: int = 5) -> list[Episode]:
        rows = self._db.execute(
            "SELECT * FROM memory_episodes ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_episode(r) for r in rows]

    def count(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM memory_episodes").fetchone()[0]

    def _session_compressed(self, session_id: str) -> bool:
        row = self._db.execute(
            "SELECT id FROM memory_episodes WHERE session_id = ? LIMIT 1", (session_id,)
        ).fetchone()
        return row is not None

    def close(self) -> None:
        self._db.close()


def _row_to_episode(row: sqlite3.Row) -> Episode:
    return Episode(
        id=row["id"],
        session_id=row["session_id"],
        summary_text=row["summary_text"],
        tags=json.loads(row["tags"]),
        timestamp=row["timestamp"],
        confidence=float(row["confidence"]),
        turn_count=int(row["turn_count"]),
        start_turn_index=int(row["start_turn_index"]),
        end_turn_index=int(row["end_turn_index"]),
    )
