#!/usr/bin/env python3
"""Generate a short random 8-bit-style alert WAV."""

from __future__ import annotations

import argparse
import math
import random
import wave
from pathlib import Path


SAMPLE_RATE = 22_050
TAU = math.tau


def _square(phase: float) -> float:
    return 1.0 if math.sin(phase) >= 0 else -1.0


def _envelope(index: int, total: int) -> float:
    attack = max(1, int(total * 0.08))
    release = max(1, int(total * 0.28))
    if index < attack:
        return index / attack
    if index > total - release:
        return max(0.0, (total - index) / release)
    return 1.0


def _clamp_8bit(value: float) -> int:
    return max(0, min(255, 128 + int(value * 112)))


def generate(path: Path, seed: str) -> None:
    rng = random.Random(seed)
    duration = rng.uniform(0.12, 0.24)
    total = int(SAMPLE_RATE * duration)
    base_freq = rng.choice([523.25, 587.33, 659.25, 783.99, 880.0])
    steps = rng.choice(
        [
            (1.0, 1.25, 1.5),
            (1.0, 1.5, 2.0),
            (1.5, 1.25, 1.0),
            (1.0, 1.0, 1.5, 2.0),
        ]
    )
    duty_noise = rng.uniform(0.02, 0.08)
    vibrato_rate = rng.uniform(10.0, 18.0)
    vibrato_depth = rng.uniform(0.004, 0.012)

    frames = bytearray()
    phase = 0.0
    for i in range(total):
        t = i / SAMPLE_RATE
        step = steps[min(len(steps) - 1, int(i * len(steps) / total))]
        freq = base_freq * step * (1.0 + math.sin(TAU * vibrato_rate * t) * vibrato_depth)
        phase += TAU * freq / SAMPLE_RATE
        tone = _square(phase)
        noise = rng.uniform(-1.0, 1.0) * duty_noise
        frames.append(_clamp_8bit((tone * 0.82 + noise) * _envelope(i, total)))

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(1)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(bytes(frames))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--seed", default=str(random.randrange(2**64)))
    args = parser.parse_args()

    generate(args.output, args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
