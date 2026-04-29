from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from promptlibretto import load_registry
from ensemble.engine import EnsembleEngine, Participant

router = APIRouter(prefix="/api/ensemble")


class ConnectionConfig(BaseModel):
    base_url: str = "http://localhost:11434"
    chat_path: str = "/api/chat"
    payload_shape: str = "auto"


class ParticipantConfig(BaseModel):
    registry: dict[str, Any]
    model: str = "llama3"
    name: str = "A"
    state: dict[str, Any] = Field(default_factory=dict)


class EnsembleRequest(BaseModel):
    a: ParticipantConfig
    b: ParticipantConfig
    seed: str
    turns: int = Field(default=8, ge=1, le=40)
    connection: ConnectionConfig = Field(default_factory=ConnectionConfig)


@router.post("/run")
async def run_ensemble(req: EnsembleRequest) -> StreamingResponse:
    async def generate() -> AsyncGenerator[str, None]:
        queue: asyncio.Queue[dict] = asyncio.Queue()
        current_speaker: list[Optional[str]] = [None]
        turn_num: list[int] = [0]

        async def on_chunk(name: str, delta: str) -> None:
            if name != current_speaker[0]:
                current_speaker[0] = name
                await queue.put({"type": "turn_start", "speaker": name, "turn": turn_num[0]})
            await queue.put({"type": "chunk", "speaker": name, "text": delta})

        async def on_turn(name: str, text: str, idx: int) -> None:
            await queue.put({"type": "turn_end", "speaker": name, "turn": idx})
            turn_num[0] = idx + 1
            current_speaker[0] = None

        async def _run() -> None:
            try:
                engine_a = load_registry(req.a.registry)
                engine_b = load_registry(req.b.registry)
                conn = req.connection
                pa = Participant(
                    name=req.a.name,
                    engine=engine_a,
                    model=req.a.model,
                    ollama_url=conn.base_url,
                    chat_path=conn.chat_path,
                    payload_shape=conn.payload_shape,
                    state=req.a.state,
                )
                pb = Participant(
                    name=req.b.name,
                    engine=engine_b,
                    model=req.b.model,
                    ollama_url=conn.base_url,
                    chat_path=conn.chat_path,
                    payload_shape=conn.payload_shape,
                    state=req.b.state,
                )
                ensemble = EnsembleEngine(pa, pb, max_turns=req.turns)
                await ensemble.run(seed=req.seed, on_chunk=on_chunk, on_turn=on_turn)
                await queue.put({"type": "done"})
            except Exception as exc:
                await queue.put({"type": "error", "message": str(exc)})

        task = asyncio.create_task(_run())
        while True:
            event = await queue.get()
            yield f"data: {json.dumps(event)}\n\n"
            if event["type"] in ("done", "error"):
                break
        await task

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
