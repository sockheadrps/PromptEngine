from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional, Sequence

from ..assets.registry import PromptAssetRegistry, PromptInjection
from ..builders.builder import BuildContext, GenerationRequest, PromptPackage
from ..config import GenerationConfig
from ..context.store import ContextStore
from ..output.history import RunHistory, RunRecord
from ..output.memory import RecentOutputMemory
from ..output.processor import OutputProcessor, ProcessingContext
from ..providers.base import (
    ProviderAdapter,
    ProviderMessage,
    ProviderRequest,
    ProviderResponse,
)
from ..random_source import DefaultRandom, RandomSource
from ..routing.router import PromptRouter
from .trace import GenerationAttempt, GenerationTrace


@dataclass
class GenerationResult:
    text: str
    accepted: bool
    route: str
    trace: Optional[GenerationTrace] = None


class PromptEngine:
    """The single entry point for the library.

    All generation goes through `generate_once`. Schedulers loop on this; debug
    steppers call it once. They share the same code path, which is the design
    document's core requirement.
    """

    def __init__(
        self,
        config: GenerationConfig,
        context_store: ContextStore,
        asset_registry: PromptAssetRegistry,
        router: PromptRouter,
        provider: ProviderAdapter,
        output_processor: Optional[OutputProcessor] = None,
        recent_memory: Optional[RecentOutputMemory] = None,
        run_history: Optional[RunHistory] = None,
        random: Optional[RandomSource] = None,
    ):
        self.config = config
        self.context_store = context_store
        self.asset_registry = asset_registry
        self.router = router
        self.provider = provider
        self.output_processor = output_processor or OutputProcessor()
        self.recent_memory = recent_memory
        self.run_history = run_history
        self.random = random or DefaultRandom()

    def update_config(self, config: GenerationConfig) -> None:
        self.config = config

    async def generate_once(self, request: GenerationRequest) -> GenerationResult:
        snapshot = self.context_store.get_state()
        injections = self._materialize_injections(request.injections)

        route = self.router.select(snapshot, request)
        build_ctx = BuildContext(
            snapshot=snapshot,
            request=request,
            assets=self.asset_registry,
            random=self.random,
            injections=injections,
        )
        package = route.builder.build(build_ctx)

        merged_config = self.config.merged_with(package.generation_overrides)
        policy = self.output_processor.policy_for(package.output_policy)

        attempts: list[GenerationAttempt] = []
        provider_response: Optional[ProviderResponse] = None
        final_text = ""
        accepted = False
        reject_reason: Optional[str] = None

        retries = max(0, merged_config.retries)
        for attempt_idx in range(retries + 1):
            provider_response = await self._call_provider(package, merged_config)
            raw = provider_response.text
            ctx = ProcessingContext(
                route=route.name,
                user_prompt=package.user,
                recent=self.recent_memory,
                metadata=dict(package.metadata),
            )
            cleaned = self.output_processor.clean(raw, ctx, policy)
            result = self.output_processor.validate(cleaned, ctx, policy)
            attempts.append(
                GenerationAttempt(
                    raw=raw,
                    cleaned=cleaned,
                    accepted=result.ok,
                    reject_reason=result.reason,
                )
            )
            if result.ok:
                accepted = True
                final_text = cleaned
                if self.recent_memory is not None:
                    self.recent_memory.add(cleaned)
                break
            reject_reason = result.reason
            final_text = cleaned

        trace: Optional[GenerationTrace] = None
        if request.debug:
            trace = GenerationTrace(
                route=route.name,
                active_context=snapshot.active,
                user_prompt=package.user,
                system_prompt=package.system,
                injections=[i.name for i in injections],
                config=merged_config.to_dict(),
                output_raw=attempts[-1].raw if attempts else "",
                output_final=final_text,
                attempts=attempts,
                usage=asdict(provider_response.usage) if provider_response else None,
                timing=asdict(provider_response.timing) if provider_response else None,
                metadata={
                    "fields": snapshot.fields,
                    "overlays": {
                        n: {
                            "text": o.text,
                            "priority": o.priority,
                            "expires_at": o.expires_at,
                        }
                        for n, o in snapshot.overlays.items()
                    },
                    "package_metadata": dict(package.metadata),
                    "reject_reason": reject_reason if not accepted else None,
                },
            )

        if self.run_history is not None:
            self.run_history.add(
                RunRecord(
                    request={
                        "mode": request.mode,
                        "inputs": dict(request.inputs or {}),
                        "injections": list(request.injections or []),
                        "config_overrides": merged_config.to_dict(),
                    },
                    text=final_text,
                    accepted=accepted,
                    route=route.name,
                )
            )

        return GenerationResult(
            text=final_text,
            accepted=accepted,
            route=route.name,
            trace=trace,
        )

    # --- internals -----------------------------------------------------
    def _materialize_injections(self, names: Sequence[str]) -> list[PromptInjection]:
        out: list[PromptInjection] = []
        for name in names or []:
            inj = self.asset_registry.materialize_injection(name)
            if inj is not None:
                out.append(inj)
        return out

    async def _call_provider(
        self,
        package: PromptPackage,
        config: GenerationConfig,
    ) -> ProviderResponse:
        messages: list[ProviderMessage] = []
        if package.system:
            messages.append(ProviderMessage(role="system", content=package.system))
        messages.append(ProviderMessage(role="user", content=package.user))

        request = ProviderRequest(
            model=config.model,
            messages=messages,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            top_p=config.top_p,
            top_k=config.top_k,
            repeat_penalty=config.repeat_penalty,
            stream=False,
            timeout_ms=config.timeout_ms,
        )
        return await self.provider.generate(request)
