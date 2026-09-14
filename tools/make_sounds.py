"""Generate the eight UI sounds `docs/E2E.md` S-74 names, straight into `web/public/sounds/`.

    python tools/make_sounds.py            # writes web/public/sounds/*.wav
    python tools/make_sounds.py --check    # regenerate into memory, compare, exit 1 on drift

Why a generator and not eight downloaded files: `docs/DEPENDENCIES.md` is a hard cap enforced by
S-110, this repository ships self-contained, and a committed binary whose provenance is "somebody
found it on a CDN in 2026" is exactly the licence question S-120/AC-171 (ruling JC-04) exists to
refuse. Every byte here is produced by this file, from the standard library only (`wave`, `math`,
`struct`), so the assets are reproducible rather than mysterious: run it again and you get the
same bytes.

Format: 22050 Hz, 16-bit signed mono PCM. Not MP3/OGG — an encoder is a dependency, `wave` is
stdlib, and the longest of these is 190 ms, which at this rate is ~8 KB. Well under S-120's 256 KB
ceiling with three orders of magnitude to spare.

Design brief (the owner's call to overrule, `RESEARCH.md` §3): restrained, quiet, non-musical,
each distinguishable from the others by shape rather than by melody. Peak amplitude is 0.2 of full
scale on purpose — these accompany a gesture the user already saw happen, they do not announce it.
Every clip opens with a 4 ms attack and closes on a decay that reaches zero, so nothing ends on a
discontinuity (a hard cut is the "tick" a cheap UI sound is made of, and it is the one artefact
that makes a set like this sound broken on small speakers).
"""

from __future__ import annotations

import argparse
import math
import struct
import sys
import wave
from pathlib import Path

RATE = 22050
PEAK = 0.2
ATTACK_S = 0.004

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "web" / "public" / "sounds"


def _envelope(index: int, total: int, decay_s: float) -> float:
    """Short linear attack, exponential decay, forced to zero at the last sample."""
    t = index / RATE
    attack = min(1.0, t / ATTACK_S) if ATTACK_S > 0 else 1.0
    decay = math.exp(-t / decay_s)
    tail = 1.0 - (index / max(1, total - 1)) ** 8  # pins the final sample at exactly 0
    return attack * decay * tail


def _tone(duration_s: float, f_start: float, f_end: float, decay_s: float, gain: float) -> list[float]:
    """One glide (constant pitch when `f_start == f_end`), enveloped. Phase is integrated rather
    than computed per-sample from a frequency, so a glide has no phase jump at any point."""
    total = int(duration_s * RATE)
    out: list[float] = []
    phase = 0.0
    for i in range(total):
        frac = i / max(1, total - 1)
        freq = f_start + (f_end - f_start) * frac
        phase += 2.0 * math.pi * freq / RATE
        out.append(math.sin(phase) * _envelope(i, total, decay_s) * gain)
    return out


def _noise(duration_s: float, decay_s: float, gain: float) -> list[float]:
    """Low-passed pseudo-noise — a soft scuff, not a hiss. The generator is a plain 32-bit LCG
    with a fixed seed: deterministic output matters more here than statistical quality, and
    `random` seeded globally would make this file's output depend on import order."""
    total = int(duration_s * RATE)
    state = 0x2545F491
    out: list[float] = []
    low = 0.0
    for i in range(total):
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        white = (state / 0xFFFFFFFF) * 2.0 - 1.0
        low += 0.12 * (white - low)  # one-pole lowpass, ~450 Hz corner at this rate
        out.append(low * 6.0 * _envelope(i, total, decay_s) * gain)
    return out


def _silence(duration_s: float) -> list[float]:
    return [0.0] * int(duration_s * RATE)


def _clip(samples: list[float]) -> bytes:
    frames = bytearray()
    for s in samples:
        v = max(-1.0, min(1.0, s * PEAK))
        frames += struct.pack("<h", int(v * 32767))
    return bytes(frames)


# The eight, in `docs/E2E.md` S-74's own order. One line of prose each, because the owner reviews
# these by reading before ever hearing them.
SOUNDS: dict[str, tuple[str, list[float]]] = {
    # A short, dry tick. The affirmative half of the pair, higher of the two.
    "checked": ("60 ms tick at 880 Hz", _tone(0.060, 880, 880, 0.018, 1.0)),
    # The same tick an octave down — audibly the same gesture, undone.
    "unchecked": ("60 ms tick at 440 Hz", _tone(0.060, 440, 440, 0.018, 1.0)),
    # A soft scuff: filtered noise, no pitch at all, so it never reads as a state change.
    "goal_dragging": ("45 ms low-passed noise scuff", _noise(0.045, 0.020, 0.55)),
    # A short fall. Downward means gone; nothing else in the set descends.
    "goal_deleted": ("140 ms fall, 660 Hz to 220 Hz", _tone(0.140, 660, 220, 0.055, 0.85)),
    # A short rise — the inverse shape of the delete, which is what makes the pair legible.
    "add_goal_clicked": ("90 ms rise, 440 Hz to 660 Hz", _tone(0.090, 440, 660, 0.040, 0.8)),
    # Two blips, low then high: something opened.
    "vertical_expanded": (
        "two 35 ms blips, 520 Hz then 780 Hz",
        _tone(0.035, 520, 520, 0.014, 0.7) + _silence(0.025) + _tone(0.035, 780, 780, 0.014, 0.7),
    ),
    # The same two, reversed: something closed.
    "vertical_collapsed": (
        "two 35 ms blips, 780 Hz then 520 Hz",
        _tone(0.035, 780, 780, 0.014, 0.7) + _silence(0.025) + _tone(0.035, 520, 520, 0.014, 0.7),
    ),
    # Three ascending blips with a longer tail — the only clip in the set that takes its time,
    # and the only one that follows another sound rather than standing alone.
    "all_completed": (
        "three 50 ms blips rising 660/880/1170 Hz",
        _tone(0.050, 660, 660, 0.020, 0.8)
        + _silence(0.020)
        + _tone(0.050, 880, 880, 0.020, 0.8)
        + _silence(0.020)
        + _tone(0.070, 1170, 1170, 0.035, 0.8),
    ),
}


def _write(path: Path, frames: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(frames)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="compare with what is on disk")
    args = parser.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    drift: list[str] = []
    for name, (description, samples) in SOUNDS.items():
        path = OUT_DIR / f"{name}.wav"
        frames = _clip(samples)
        if args.check:
            if not path.exists():
                drift.append(f"{path.name}: missing")
                continue
            with wave.open(str(path), "rb") as r:
                on_disk = r.readframes(r.getnframes())
            if on_disk != frames:
                drift.append(f"{path.name}: {len(on_disk)} bytes on disk, {len(frames)} generated")
            continue
        _write(path, frames)
        print(f"{path.relative_to(REPO_ROOT)}  {path.stat().st_size:>6} bytes  — {description}")

    if args.check:
        for line in drift:
            print(line, file=sys.stderr)
        return 1 if drift else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
