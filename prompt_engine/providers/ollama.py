from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from .base import (
    ProviderAdapter,
    ProviderRequest,
    ProviderResponse,
    ProviderTiming,
    ProviderUsage,
)


class OllamaProvider(ProviderAdapter):
    """Adapter for an Ollama-compatible HTTP backend.

    Uses the `/api/chat` endpoint by default. Most local Ollama installs run
    on http://localhost:11434, but the URL is fully configurable so it can
    point at any compatible endpoint (for example a custom port like 8080).
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        chat_path: str = "/api/chat",
        client: Optional[httpx.AsyncClient] = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._chat_path = chat_path if chat_path.startswith("/") else "/" + chat_path
        self._owned_client = client is None
        self._client = client or httpx.AsyncClient()

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        options: dict[str, Any] = {
            "temperature": request.temperature,
            "num_predict": request.max_tokens,
        }
        if request.top_p is not None:
            options["top_p"] = request.top_p
        if request.top_k is not None:
            options["top_k"] = request.top_k
        if request.repeat_penalty is not None:
            options["repeat_penalty"] = request.repeat_penalty

        payload = {
            "model": request.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "stream": False,
            "options": options,
        }

        url = f"{self._base_url}{self._chat_path}"
        timeout = max(1.0, request.timeout_ms / 1000.0)

        started = time.perf_counter()
        response = await self._client.post(url, json=payload, timeout=timeout)
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        response.raise_for_status()
        data = response.json()

        text = self._extract_text(data)
        usage = self._extract_usage(data)
        timing = ProviderTiming(
            total_ms=_ns_to_ms(data.get("total_duration")) or elapsed_ms,
            load_ms=_ns_to_ms(data.get("load_duration")),
            prompt_eval_ms=_ns_to_ms(data.get("prompt_eval_duration")),
            eval_ms=_ns_to_ms(data.get("eval_duration")),
        )
        return ProviderResponse(text=text, usage=usage, timing=timing, raw=data)

    @staticmethod
    def _extract_text(data: dict) -> str:
        # Ollama /api/chat: {"message": {"content": "..."}}
        msg = data.get("message")
        if isinstance(msg, dict):
            content = msg.get("content")
            if content:
                return content
        # OpenAI-compatible (llama.cpp, vLLM, etc.): {"choices": [{"message": {"content": "..."}}]}
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0] or {}
            cmsg = first.get("message") if isinstance(first, dict) else None
            if isinstance(cmsg, dict):
                content = cmsg.get("content")
                if content:
                    return content
            # OpenAI completions style: {"choices": [{"text": "..."}]}
            text = first.get("text") if isinstance(first, dict) else None
            if text:
                return text
            # Some servers nest as delta (streaming aggregates)
            delta = first.get("delta") if isinstance(first, dict) else None
            if isinstance(delta, dict) and delta.get("content"):
                return delta["content"]
        # Ollama /api/generate: {"response": "..."}
        if data.get("response"):
            return data["response"]
        # Last-ditch: a top-level "content" field
        if isinstance(data.get("content"), str):
            return data["content"]
        return ""

    @staticmethod
    def _extract_usage(data: dict) -> ProviderUsage:
        # OpenAI-compatible usage block
        u = data.get("usage")
        if isinstance(u, dict):
            return ProviderUsage(
                prompt_tokens=u.get("prompt_tokens"),
                completion_tokens=u.get("completion_tokens"),
                total_tokens=u.get("total_tokens")
                or _safe_sum(u.get("prompt_tokens"), u.get("completion_tokens")),
            )
        # Ollama-native usage fields
        prompt = data.get("prompt_eval_count")
        completion = data.get("eval_count")
        if prompt is not None or completion is not None:
            return ProviderUsage(
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=_safe_sum(prompt, completion),
            )
        # llama.cpp also exposes tokens_predicted / tokens_evaluated in some builds
        prompt = data.get("tokens_evaluated")
        completion = data.get("tokens_predicted")
        if prompt is not None or completion is not None:
            return ProviderUsage(
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=_safe_sum(prompt, completion),
            )
        return ProviderUsage()


def _ns_to_ms(value: Optional[int]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value) / 1_000_000.0
    except (TypeError, ValueError):
        return None


def _safe_sum(a: Optional[int], b: Optional[int]) -> Optional[int]:
    if a is None and b is None:
        return None
    return (a or 0) + (b or 0)
