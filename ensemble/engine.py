from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from promptlibretto.providers.base import ProviderMessage, ProviderRequest
from promptlibretto.providers.ollama import OllamaProvider
from promptlibretto.registry.engine import Engine


@dataclass
class Participant:
    name: str
    engine: Engine
    model: str
    ollama_url: str = "http://localhost:11434"
    chat_path: str = "/api/chat"
    payload_shape: str = "auto"
    state: dict = field(default_factory=dict)
    _provider: Optional[OllamaProvider] = field(default=None, init=False, repr=False)

    def provider(self) -> OllamaProvider:
        if self._provider is None:
            self._provider = OllamaProvider(
                base_url=self.ollama_url,
                chat_path=self.chat_path,
                payload_shape=self.payload_shape,
            )
        return self._provider


@dataclass
class Turn:
    speaker: str
    text: str


OnTurnFn = Callable[[str, str, int], Awaitable[None]]
OnChunkFn = Callable[[str, str], Awaitable[None]]


class EnsembleEngine:
    """Two registry-driven models taking turns responding to each other.

    Each participant's registry hydrates into their system prompt. The
    conversation history is passed as user/assistant messages so each model
    sees the full exchange from its own perspective.
    """

    def __init__(
        self,
        a: Participant,
        b: Participant,
        max_turns: int = 8,
    ) -> None:
        self.a = a
        self.b = b
        self.max_turns = max_turns
        self.history: list[Turn] = []

    def _build_messages(
        self, speaker: Participant, other: Participant, new_input: str
    ) -> list[ProviderMessage]:
        system_prompt = speaker.engine.hydrate(speaker.state or None)
        messages = [ProviderMessage(role="system", content=system_prompt)]
        for turn in self.history:
            role = "assistant" if turn.speaker == speaker.name else "user"
            messages.append(ProviderMessage(role=role, content=turn.text))
        messages.append(ProviderMessage(role="user", content=new_input))
        return messages

    def _build_request(self, speaker: Participant, messages: list[ProviderMessage]) -> ProviderRequest:
        cfg, _ = speaker.engine._cfg_policy_for(None)
        return ProviderRequest(
            model=speaker.model,
            messages=messages,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            top_p=cfg.top_p,
            top_k=cfg.top_k,
            repeat_penalty=cfg.repeat_penalty,
            timeout_ms=cfg.timeout_ms,
        )

    async def run(
        self,
        seed: str,
        on_chunk: Optional[OnChunkFn] = None,
        on_turn: Optional[OnTurnFn] = None,
    ) -> list[Turn]:
        participants = [self.a, self.b]
        current_input = seed

        for turn_idx in range(self.max_turns):
            speaker = participants[turn_idx % 2]
            other = participants[(turn_idx + 1) % 2]

            messages = self._build_messages(speaker, other, current_input)
            request = self._build_request(speaker, messages)
            provider = speaker.provider()

            if on_chunk is not None:
                text = await self._stream_turn(provider, request, speaker.name, on_chunk)
            else:
                response = await provider.generate(request)
                text = response.text.strip()

            self.history.append(Turn(speaker=speaker.name, text=text))

            if on_turn is not None:
                await on_turn(speaker.name, text, turn_idx)

            current_input = text

        return self.history

    @staticmethod
    async def _stream_turn(
        provider: OllamaProvider,
        request: ProviderRequest,
        name: str,
        on_chunk: OnChunkFn,
    ) -> str:
        buffer: list[str] = []
        async for chunk in provider.stream(request):
            if chunk.text:
                buffer.append(chunk.text)
                await on_chunk(name, chunk.text)
            if chunk.done:
                break
        return "".join(buffer).strip()
