"""Verify that a rendered automation patch changes only its approved range."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import wave


def _read(path: Path) -> tuple[int, list[tuple[float, float]]]:
    with wave.open(str(path), "rb") as stream:
        channels = stream.getnchannels()
        width = stream.getsampwidth()
        rate = stream.getframerate()
        frames = stream.getnframes()
        if channels != 2 or width not in (2, 3, 4) or frames == 0:
            raise ValueError("requires nonempty stereo PCM WAV")
        raw = stream.readframes(frames)
    scale = 2 ** (width * 8 - 1)
    values = [int.from_bytes(raw[i:i + width], "little", signed=True) / scale
              for i in range(0, len(raw), width)]
    return rate, list(zip(values[::2], values[1::2]))


def _rms(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values) / len(values)) if values else 0.0


def compare(baseline_path: Path, processed_path: Path, *, start: float, end: float) -> dict:
    base_rate, baseline = _read(baseline_path)
    processed_rate, processed = _read(processed_path)
    if base_rate != processed_rate or len(baseline) != len(processed):
        raise ValueError("renders must have identical sample rate and frame count")
    duration = len(baseline) / base_rate
    if not 0.1 <= start < end <= duration - 0.1:
        raise ValueError("comparison range must leave exterior audio on both sides")

    guard = min(0.1, (end - start) / 10)
    exterior, interior = [], []
    for index, (before, after) in enumerate(zip(baseline, processed)):
        time_sec = index / base_rate
        target = exterior if time_sec <= start - guard or time_sec >= end + guard else (
            interior if start + guard <= time_sec <= end - guard else None)
        if target is not None:
            target.extend((after[0] - before[0], after[1] - before[1]))
    baseline_values = [sample for frame in baseline for sample in frame]
    exterior_delta = _rms(exterior)
    interior_delta = _rms(interior)
    reference = _rms(baseline_values)
    exterior_ratio = exterior_delta / reference if reference else math.inf
    interior_ratio = interior_delta / reference if reference else 0.0
    ok = exterior_ratio < 1e-4 and interior_ratio > 0.05
    return {
        "ok": ok,
        "sample_rate": base_rate,
        "frames": len(baseline),
        "duration_sec": duration,
        "approved_range_sec": [start, end],
        "guard_sec": guard,
        "exterior_delta_rms": exterior_delta,
        "exterior_delta_ratio": exterior_ratio,
        "interior_delta_rms": interior_delta,
        "interior_delta_ratio": interior_ratio,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--start", type=float, default=1.0)
    parser.add_argument("--end", type=float, default=3.0)
    args = parser.parse_args()
    result = compare(args.directory / "baseline.wav", args.directory / "processed.wav",
                     start=args.start, end=args.end)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
