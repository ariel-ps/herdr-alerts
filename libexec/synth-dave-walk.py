#!/usr/bin/env python3
"""Synthesize a PC-speaker-style footstep pair for the dangerousdave "walk" clip.

The original 1988 game's run cycle has no sound of its own — confirmed against
both the upstream webdave sounds/ directory and its source (no walk/step/foot
reference anywhere), matching the real DOS game: PC speaker titles of that era
routinely left continuous movement silent and only sounded discrete events.
There is nothing to download here, so this reproduces one in period style
instead of leaving the "walk" alert mute: a true square wave (PC speaker had no
other waveform) as two short alternating-pitch blips, left-right-footfall
style. Stdlib only (wave + struct + math), no third-party deps.

usage: synth-dave-walk.py <dest-dir>
"""

import math
import struct
import sys
import wave
from pathlib import Path

RATE = 11025  # low, period-correct sample rate; keeps the file tiny
AMPLITUDE = 0.5  # of full scale -- PC speaker was loud; this just avoids clipping
STEPS = ((190, 0.045), (150, 0.045))  # (Hz, seconds) per footfall, heel then toe
GAP = 0.035  # seconds of silence between the two footfalls
FADE = int(0.003 * RATE)  # samples; softens the cut so it reads as a step, not a click


def square_wave(freq: float, duration: float) -> list[int]:
    n = int(RATE * duration)
    samples = []
    for i in range(n):
        value = 1.0 if math.sin(2 * math.pi * freq * i / RATE) >= 0 else -1.0
        if i < FADE:
            value *= i / FADE
        elif i >= n - FADE:
            value *= (n - i) / FADE
        samples.append(int(value * AMPLITUDE * 32767))
    return samples


def silence(duration: float) -> list[int]:
    return [0] * int(RATE * duration)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: synth-dave-walk.py <dest-dir>", file=sys.stderr)
        return 2
    dest = Path(sys.argv[1]).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / "walk.wav"

    samples: list[int] = []
    for i, (freq, duration) in enumerate(STEPS):
        if i:
            samples += silence(GAP)
        samples += square_wave(freq, duration)

    with wave.open(str(out), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    print(f"synth-dave-walk: wrote {out} ({len(samples)} samples)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
