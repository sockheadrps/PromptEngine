"""ensemble — two registry-driven models talking to each other.

Usage:
    python -m ensemble.cli \\
        --registry-a ensemble/configs/philosopher.json \\
        --registry-b ensemble/configs/skeptic.json \\
        --model-a llama3 \\
        --model-b llama3 \\
        --turns 8 \\
        --seed "Is free will an illusion?"
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from promptlibretto import load_registry

from .engine import EnsembleEngine, Participant

DIVIDER = "─" * 60


def build_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run two registry-driven models in conversation."
    )
    p.add_argument("--registry-a", required=True, metavar="PATH",
                   help="Registry JSON for participant A.")
    p.add_argument("--registry-b", required=True, metavar="PATH",
                   help="Registry JSON for participant B.")
    p.add_argument("--model-a", default="llama3", metavar="MODEL",
                   help="Ollama model name for A. (default: llama3)")
    p.add_argument("--model-b", default="llama3", metavar="MODEL",
                   help="Ollama model name for B. (default: llama3)")
    p.add_argument("--ollama-url", default="http://localhost:11434", metavar="URL")
    p.add_argument("--turns", type=int, default=8,
                   help="Total number of turns (shared between both models).")
    p.add_argument("--seed", required=True,
                   help="Opening message sent to model A to start the exchange.")
    p.add_argument("--no-stream", action="store_true",
                   help="Disable streaming; print each response after it completes.")
    return p.parse_args()


async def run(args: argparse.Namespace) -> None:
    engine_a = load_registry(args.registry_a)
    engine_b = load_registry(args.registry_b)

    a = Participant(name="A", engine=engine_a, model=args.model_a, ollama_url=args.ollama_url)
    b = Participant(name="B", engine=engine_b, model=args.model_b, ollama_url=args.ollama_url)

    ensemble = EnsembleEngine(a, b, max_turns=args.turns)

    print(f"\n  seed → {args.seed}\n{DIVIDER}")

    if args.no_stream:
        async def on_turn(name: str, text: str, idx: int) -> None:
            label = f"[{name}]  turn {idx + 1}"
            print(f"\n{label}\n{text}\n{DIVIDER}")

        await ensemble.run(seed=args.seed, on_turn=on_turn)

    else:
        current_speaker: list[str] = [""]
        turn_index: list[int] = [0]

        async def on_chunk(name: str, delta: str) -> None:
            if name != current_speaker[0]:
                current_speaker[0] = name
                label = f"\n[{name}]  turn {turn_index[0] + 1}\n"
                print(label, end="", flush=True)
                turn_index[0] += 1
            print(delta, end="", flush=True)

        async def on_turn(name: str, text: str, idx: int) -> None:
            print(f"\n{DIVIDER}", flush=True)

        await ensemble.run(seed=args.seed, on_chunk=on_chunk, on_turn=on_turn)

    print("\ndone.")


def main() -> None:
    asyncio.run(run(build_args()))


if __name__ == "__main__":
    main()
