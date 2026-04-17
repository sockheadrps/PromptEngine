"""Generic modular prompt engine.

Public surface is organised by concern: config, context, assets, routing,
builders, providers, output, runtime, random. Most users only need a few
imports from this top-level package.
"""

from .config import GenerationConfig
from .random_source import RandomSource, DefaultRandom, SeededRandom
from .context.overlay import ContextOverlay, ContextSnapshot, make_turn_overlay
from .context.template import TemplateRenderer, TemplateField, TemplateRenderOptions
from .context.store import ContextStore
from .assets.registry import PromptAssetRegistry, InjectionTemplate, PromptInjection
from .routing.route import PromptRoute
from .routing.router import PromptRouter
from .builders.builder import PromptBuilder, PromptPackage, GenerationRequest
from .builders.composite import CompositeBuilder, section, join_sections
from .providers.base import ProviderAdapter, ProviderRequest, ProviderResponse
from .providers.ollama import OllamaProvider
from .providers.mock import MockProvider
from .output.processor import OutputProcessor, ValidationResult, OutputPolicy
from .output.memory import RecentOutputMemory
from .output.history import RunHistory, RunRecord
from .runtime.trace import GenerationTrace, GenerationAttempt
from .runtime.engine import PromptEngine, GenerationResult

__all__ = [
    "GenerationConfig",
    "RandomSource",
    "DefaultRandom",
    "SeededRandom",
    "ContextOverlay",
    "ContextSnapshot",
    "make_turn_overlay",
    "TemplateRenderer",
    "TemplateField",
    "TemplateRenderOptions",
    "ContextStore",
    "PromptAssetRegistry",
    "InjectionTemplate",
    "PromptInjection",
    "PromptRoute",
    "PromptRouter",
    "PromptBuilder",
    "PromptPackage",
    "GenerationRequest",
    "CompositeBuilder",
    "section",
    "join_sections",
    "ProviderAdapter",
    "ProviderRequest",
    "ProviderResponse",
    "OllamaProvider",
    "MockProvider",
    "OutputProcessor",
    "ValidationResult",
    "OutputPolicy",
    "RecentOutputMemory",
    "RunHistory",
    "RunRecord",
    "GenerationTrace",
    "GenerationAttempt",
    "PromptEngine",
    "GenerationResult",
]
