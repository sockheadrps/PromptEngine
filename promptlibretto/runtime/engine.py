from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, AsyncIterator, Mapping, Optional, Sequence, Union

from ..assets.registry import PromptAssetRegistry, PromptInjection
from ..builders.builder import BuildContext, GenerationRequest, PromptPackage
from ..builders.composite import CompositeBuilder, SectionFn, section
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
    supports_streaming,
)
from ..providers.mock import MockProvider
from ..random_source import DefaultRandom, RandomSource
from ..routing.route import PromptRoute
from ..routing.router import PromptRouter
from .middleware import apply_after, apply_before
from .trace import GenerationAttempt, GenerationTrace


@dataclass
class GenerationResult:
    text: str
    accepted: bool
    route: str
    trace: Optional[GenerationTrace] = None
    usage: Optional[dict] = None
    timing: Optional[dict] = None


@dataclass
class GenerationChunk:
    delta: str = ""
    done: bool = False
    result: Optional[GenerationResult] = None


class PromptEngine:

    def __init__(
        self,
        config: Union[GenerationConfig, Mapping[str, Any], None] = None,
        context_store: Union[ContextStore, str, Mapping[str, Any], None] = None,
        asset_registry: Optional[PromptAssetRegistry] = None,
        router: Union[PromptRouter, Sequence[PromptRoute], None] = None,
        provider: Union[ProviderAdapter, str, None] = None,
        output_processor: Optional[OutputProcessor] = None,
        recent_memory: Optional[RecentOutputMemory] = None,
        run_history: Optional[RunHistory] = None,
        random: Optional[RandomSource] = None,
        middlewares: Optional[Sequence[object]] = None,
        *,
        routes: Union[Mapping[str, Any], Sequence, None] = None,
    ):
        self.provider = _coerce_provider(provider)
        self.config = _coerce_config(config, self.provider)
        self.context_store = _coerce_context_store(context_store)
        self.asset_registry = asset_registry or PromptAssetRegistry()
        self.router = _coerce_router(router, routes)
        self.output_processor = output_processor or OutputProcessor()
        self.recent_memory = recent_memory
        self.run_history = run_history
        self.random = random or DefaultRandom()
        self.middlewares: list[object] = list(middlewares or [])

    def update_config(self, config: GenerationConfig) -> None:
        self.config = config

    def add_middleware(self, middleware: object) -> None:
        self.middlewares.append(middleware)

    async def generate_once(
        self,
        request: Union[GenerationRequest, Mapping[str, Any], str, None] = None,
    ) -> GenerationResult:
        request = _coerce_request(request)
        if self.middlewares:
            request = await apply_before(self.middlewares, request)
        result = await self._generate_core(request)
        if self.middlewares:
            result = await apply_after(self.middlewares, request, result)
        return result

    async def _generate_core(self, request: GenerationRequest) -> GenerationResult:
        snapshot = self.context_store.get_state()
        injections = self._materialize_injections(request.injections)

        route = self.router.select(snapshot, request)
        package, snapshot, merged_config, config_layers, trim_info = self._build_with_budget(
            route, request, snapshot, injections
        )
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
                    "config_layers": config_layers,
                    "reject_reason": reject_reason if not accepted else None,
                    "budget": trim_info,
                },
            )

        if self.run_history is not None:
            self.run_history.add(
                RunRecord(
                    request=self._history_request(request),
                    text=final_text,
                    accepted=accepted,
                    route=route.name,
                    metadata={"resolved_config": merged_config.to_dict()},
                )
            )

        return GenerationResult(
            text=final_text,
            accepted=accepted,
            route=route.name,
            trace=trace,
            usage=asdict(provider_response.usage) if provider_response else None,
            timing=asdict(provider_response.timing) if provider_response else None,
        )

    async def generate_stream(
        self,
        request: Union[GenerationRequest, Mapping[str, Any], str, None] = None,
    ) -> AsyncIterator[GenerationChunk]:
        """Stream deltas, then a terminal chunk with the final result.

        Makes exactly one provider call; output-policy retries are skipped.
        If `result.accepted` is False, fall back to `generate_once`.
        """
        request = _coerce_request(request)
        if not supports_streaming(self.provider):
            raise RuntimeError(
                f"provider {type(self.provider).__name__} does not support streaming"
            )

        if self.middlewares:
            request = await apply_before(self.middlewares, request)

        snapshot = self.context_store.get_state()
        injections = self._materialize_injections(request.injections)
        route = self.router.select(snapshot, request)
        package, snapshot, merged_config, config_layers, trim_info = self._build_with_budget(
            route, request, snapshot, injections
        )
        policy = self.output_processor.policy_for(package.output_policy)

        provider_request = self._build_provider_request(package, merged_config)
        final_response: Optional[ProviderResponse] = None
        buffer = ""
        async for chunk in self.provider.stream(provider_request):
            if chunk.done:
                final_response = chunk.response
                break
            if chunk.text:
                buffer += chunk.text
                yield GenerationChunk(delta=chunk.text)

        raw = final_response.text if final_response else buffer
        ctx = ProcessingContext(
            route=route.name,
            user_prompt=package.user,
            recent=self.recent_memory,
            metadata=dict(package.metadata),
        )
        cleaned = self.output_processor.clean(raw, ctx, policy)
        validation = self.output_processor.validate(cleaned, ctx, policy)

        if validation.ok and self.recent_memory is not None:
            self.recent_memory.add(cleaned)

        trace: Optional[GenerationTrace] = None
        if request.debug:
            trace = GenerationTrace(
                route=route.name,
                active_context=snapshot.active,
                user_prompt=package.user,
                system_prompt=package.system,
                injections=[i.name for i in injections],
                config=merged_config.to_dict(),
                output_raw=raw,
                output_final=cleaned,
                attempts=[GenerationAttempt(
                    raw=raw, cleaned=cleaned,
                    accepted=validation.ok, reject_reason=validation.reason,
                )],
                usage=asdict(final_response.usage) if final_response else None,
                timing=asdict(final_response.timing) if final_response else None,
                metadata={
                    "fields": snapshot.fields,
                    "overlays": {
                        n: {"text": o.text, "priority": o.priority, "expires_at": o.expires_at}
                        for n, o in snapshot.overlays.items()
                    },
                    "package_metadata": dict(package.metadata),
                    "config_layers": config_layers,
                    "reject_reason": None if validation.ok else validation.reason,
                    "streamed": True,
                    "budget": trim_info,
                },
            )

        result = GenerationResult(
            text=cleaned,
            accepted=validation.ok,
            route=route.name,
            trace=trace,
            usage=asdict(final_response.usage) if final_response else None,
            timing=asdict(final_response.timing) if final_response else None,
        )

        if self.run_history is not None:
            self.run_history.add(
                RunRecord(
                    request=self._history_request(request),
                    text=cleaned,
                    accepted=validation.ok,
                    route=route.name,
                    metadata={
                        "resolved_config": merged_config.to_dict(),
                        "streamed": True,
                    },
                )
            )

        if self.middlewares:
            result = await apply_after(self.middlewares, request, result)

        yield GenerationChunk(done=True, result=result)

    def _build_with_budget(
        self,
        route,
        request: GenerationRequest,
        snapshot,
        injections: list[PromptInjection],
    ):
        """Build the package; if over `max_prompt_chars`, drop lowest-priority
        overlays until it fits. Ties break by name for determinism.
        """
        def build(snap):
            ctx = BuildContext(
                snapshot=snap,
                request=request,
                assets=self.asset_registry,
                random=self.random,
                injections=injections,
            )
            pkg = route.builder.build(ctx)
            if request.section_overrides:
                from dataclasses import replace as _replace
                meta = dict(pkg.metadata or {})
                meta["section_overrides"] = sorted(request.section_overrides.keys())
                pkg = _replace(
                    pkg,
                    system=request.section_overrides["system"] if "system" in request.section_overrides else pkg.system,
                    user=request.section_overrides["user"] if "user" in request.section_overrides else pkg.user,
                    metadata=meta,
                )
            cfg = (
                self.config
                .merged_with(pkg.generation_overrides)
                .merged_with(request.config_overrides)
            )
            layers = {
                "base_config": self.config.to_dict(),
                "package_overrides": dict(pkg.generation_overrides or {}),
                "request_overrides": dict(request.config_overrides or {}),
                "resolved_config": cfg.to_dict(),
            }
            return pkg, cfg, layers

        package, merged_config, config_layers = build(snapshot)
        budget = merged_config.max_prompt_chars
        if budget is None or budget <= 0:
            return package, snapshot, merged_config, config_layers, None

        def size(pkg):
            return len(pkg.system or "") + len(pkg.user or "")

        dropped: list[str] = []
        current_snapshot = snapshot
        while size(package) > budget and current_snapshot.overlays:
            victim = min(
                current_snapshot.overlays.items(),
                key=lambda kv: (kv[1].priority, kv[0]),
            )[0]
            remaining = {n: o for n, o in current_snapshot.overlays.items() if n != victim}
            current_snapshot = current_snapshot.with_overlays(remaining)
            dropped.append(victim)
            package, merged_config, config_layers = build(current_snapshot)

        trim_info = {
            "budget_chars": budget,
            "final_chars": size(package),
            "dropped": dropped,
            "over_budget": size(package) > budget,
        }
        return package, current_snapshot, merged_config, config_layers, trim_info

    @staticmethod
    def _history_request(request: GenerationRequest) -> dict:
        return {
            "mode": request.mode,
            "inputs": dict(request.inputs or {}),
            "injections": list(request.injections or []),
            "config_overrides": dict(request.config_overrides or {}),
        }

    def _materialize_injections(self, names: Sequence[str]) -> list[PromptInjection]:
        out: list[PromptInjection] = []
        for name in names or []:
            inj = self.asset_registry.materialize_injection(name)
            if inj is not None:
                out.append(inj)
        return out

    def _build_provider_request(
        self,
        package: PromptPackage,
        config: GenerationConfig,
        *,
        stream: bool = False,
    ) -> ProviderRequest:
        messages: list[ProviderMessage] = []
        if package.system:
            messages.append(ProviderMessage(role="system", content=package.system))
        messages.append(ProviderMessage(role="user", content=package.user))
        return ProviderRequest(
            model=config.model,
            messages=messages,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            top_p=config.top_p,
            top_k=config.top_k,
            repeat_penalty=config.repeat_penalty,
            stream=stream,
            timeout_ms=config.timeout_ms,
        )

    async def _call_provider(
        self,
        package: PromptPackage,
        config: GenerationConfig,
    ) -> ProviderResponse:
        request = self._build_provider_request(package, config, stream=False)
        return await self.provider.generate(request)


def _coerce_provider(provider: Any) -> ProviderAdapter:
    if provider is None:
        return MockProvider()
    if isinstance(provider, str):
        name = provider.lower()
        if name == "mock":
            return MockProvider()
        if name == "ollama":
            from ..providers.ollama import OllamaProvider
            return OllamaProvider()
        raise ValueError(f"unknown provider string: {provider!r}")
    return provider


def _coerce_config(config: Any, provider: ProviderAdapter) -> GenerationConfig:
    if isinstance(config, GenerationConfig):
        return config
    default_provider = "mock" if isinstance(provider, MockProvider) else "ollama"
    default_model = "mock" if isinstance(provider, MockProvider) else "default"
    if config is None:
        return GenerationConfig(provider=default_provider, model=default_model)
    if isinstance(config, Mapping):
        fields = {"provider": default_provider, "model": default_model, **dict(config)}
        known = {f for f in GenerationConfig.__dataclass_fields__}
        return GenerationConfig(**{k: v for k, v in fields.items() if k in known})
    raise TypeError(f"config must be GenerationConfig, Mapping, or None (got {type(config).__name__})")


def _coerce_context_store(store: Any) -> ContextStore:
    if isinstance(store, ContextStore):
        return store
    if store is None:
        return ContextStore()
    if isinstance(store, str):
        return ContextStore(base=store)
    if isinstance(store, Mapping):
        return ContextStore(**dict(store))
    raise TypeError(
        f"context_store must be ContextStore, str, Mapping, or None (got {type(store).__name__})"
    )


def _coerce_section(value: Any) -> SectionFn:
    if callable(value):
        return value
    if isinstance(value, str):
        return section(value)
    raise TypeError(f"section must be str or callable (got {type(value).__name__})")


def _coerce_sections(value: Any) -> tuple:
    if value is None:
        return ()
    if isinstance(value, (str,)) or callable(value):
        return (_coerce_section(value),)
    return tuple(_coerce_section(v) for v in value)


def _coerce_builder(name: str, value: Any) -> CompositeBuilder:
    if isinstance(value, CompositeBuilder):
        return value
    if isinstance(value, (str,)) or callable(value):
        return CompositeBuilder(name=name, user_sections=(_coerce_section(value),))
    if isinstance(value, (list, tuple)):
        return CompositeBuilder(name=name, user_sections=_coerce_sections(value))
    if isinstance(value, Mapping):
        kwargs = dict(value)
        kwargs.setdefault("name", name)
        if "user_sections" in kwargs:
            kwargs["user_sections"] = _coerce_sections(kwargs["user_sections"])
        if "system_sections" in kwargs:
            kwargs["system_sections"] = _coerce_sections(kwargs["system_sections"])
        return CompositeBuilder(**kwargs)
    raise TypeError(
        f"route value must be str, callable, list/tuple, Mapping, or CompositeBuilder "
        f"(got {type(value).__name__})"
    )


def _coerce_route(name: str, value: Any) -> PromptRoute:
    if isinstance(value, PromptRoute):
        return value
    return PromptRoute(name=name, builder=_coerce_builder(name, value))


def _coerce_router(
    router: Any,
    routes: Union[Mapping[str, Any], Sequence, None],
) -> PromptRouter:
    if isinstance(router, PromptRouter):
        return router
    if isinstance(router, (list, tuple)) and all(isinstance(r, PromptRoute) for r in router):
        built = PromptRouter(default_route=router[0].name if router else None)
        built.register_many(router)
        return built

    if router is None and routes is None:
        built = PromptRouter(default_route="default")
        built.register(_coerce_route("default", ""))
        return built

    src = routes if router is None else router
    if isinstance(src, Mapping):
        items = list(src.items())
        if not items:
            raise ValueError("routes mapping is empty")
        built = PromptRouter(default_route=items[0][0])
        for name, value in items:
            built.register(_coerce_route(name, value))
        return built
    if isinstance(src, (list, tuple)):
        built_routes = [v if isinstance(v, PromptRoute) else _coerce_route(f"route_{i}", v)
                        for i, v in enumerate(src)]
        if not built_routes:
            raise ValueError("routes sequence is empty")
        built = PromptRouter(default_route=built_routes[0].name)
        built.register_many(built_routes)
        return built
    raise TypeError(
        f"router/routes must be PromptRouter, Mapping, Sequence, or None "
        f"(got router={type(router).__name__}, routes={type(routes).__name__})"
    )


def _coerce_request(request: Any) -> GenerationRequest:
    if isinstance(request, GenerationRequest):
        return request
    if request is None:
        return GenerationRequest()
    if isinstance(request, str):
        return GenerationRequest(inputs={"input": request})
    if isinstance(request, Mapping):
        return GenerationRequest(**dict(request))
    raise TypeError(
        f"request must be GenerationRequest, Mapping, str, or None (got {type(request).__name__})"
    )
