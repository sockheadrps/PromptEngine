from __future__ import annotations

import time
from typing import Callable, Optional

from .base import (
    ProviderAdapter,
    ProviderRequest,
    ProviderResponse,
    ProviderTiming,
    ProviderUsage,
)


class MockProvider(ProviderAdapter):
    """Deterministic provider useful for tests and offline development."""

    def __init__(
        self,
        responder: Optional[Callable[[ProviderRequest], str]] = None,
        latency_ms: float = 5.0,
    ):
        self._responder = responder or self._echo
        self._latency_ms = latency_ms

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        started = time.perf_counter()
        text = self._responder(request)
        elapsed_ms = (time.perf_counter() - started) * 1000.0 + self._latency_ms
        return ProviderResponse(
            text=text,
            usage=ProviderUsage(
                prompt_tokens=sum(len(m.content.split()) for m in request.messages),
                completion_tokens=len(text.split()),
                total_tokens=None,
            ),
            timing=ProviderTiming(total_ms=elapsed_ms),
            raw={"mock": True},
        )

    @staticmethod
    def _echo(request: ProviderRequest) -> str:
        last_user = next(
            (m.content for m in reversed(request.messages) if m.role == "user"),
            "",
        )
        return f"[mock:{request.model}] {last_user[:280]}"
