#!/usr/bin/env python3
"""Qualify one real VST3 instrument through Pedalboard without a GUI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import tempfile
import time
from pathlib import Path

import numpy as np
import pedalboard
from pedalboard import load_plugin
from pedalboard.io import AudioFile


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def render(plugin, midi, duration: float, rate: int) -> np.ndarray:
    audio = plugin.process(
        midi,
        duration=duration,
        sample_rate=rate,
        num_channels=2,
        buffer_size=512,
        reset=True,
    )
    if audio.shape != (2, round(duration * rate)):
        raise RuntimeError(f"unexpected render shape {audio.shape}")
    if not np.isfinite(audio).all():
        raise RuntimeError("render contains non-finite samples")
    return audio


def energy(audio: np.ndarray, rate: int, start: float, end: float) -> float:
    window = audio[:, round(start * rate):round(end * rate)]
    return float(np.sqrt(np.mean(np.square(window, dtype=np.float64))))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-rate", type=int, default=48000)
    args = parser.parse_args()

    plugin_path = args.plugin.expanduser().resolve()
    state_path = args.state.expanduser().resolve()
    output = args.output.expanduser().resolve()
    binary = next((plugin_path / "Contents" / "MacOS").iterdir())
    plugin_binary_hash = sha256(binary.read_bytes())

    started = time.monotonic()
    instrument = load_plugin(str(plugin_path), initialization_timeout=20.0)
    if not instrument.is_instrument:
        raise RuntimeError(f"{instrument.name} is not an instrument")
    restored = state_path.exists()
    if restored:
        instrument.raw_state = state_path.read_bytes()
    else:
        atomic_bytes(state_path, instrument.raw_state)
    state_hash = sha256(instrument.raw_state)

    # MIDI is timestamped in seconds and submitted as one complete schedule.
    # CC64 is the only controller this fixture claims to qualify.
    plain_midi = [
        (bytes([0x90, 60, 100]), 0.250),
        (bytes([0x80, 60, 0]), 0.750),
    ]
    sustain_midi = [
        (bytes([0x90, 60, 100]), 0.250),
        (bytes([0xB0, 64, 127]), 0.700),
        (bytes([0x80, 60, 0]), 0.750),
        (bytes([0xB0, 64, 0]), 1.250),
    ]
    duration = 2.0
    plain = render(instrument, plain_midi, duration, args.sample_rate)

    # Reload and restore before the evidence render, avoiding carryover from the
    # comparison pass and exercising GUI-free state application in this process.
    instrument = load_plugin(str(plugin_path), initialization_timeout=20.0)
    instrument.raw_state = state_path.read_bytes()
    sustained = render(instrument, sustain_midi, duration, args.sample_rate)
    plain_sustain_window = energy(plain, args.sample_rate, 0.850, 1.150)
    sustained_window = energy(sustained, args.sample_rate, 0.850, 1.150)
    cc64_ratio = sustained_window / max(plain_sustain_window, 1e-12)

    absolute = np.max(np.abs(sustained), axis=0)
    active = np.flatnonzero(absolute > 1e-5)
    first = int(active[0]) if len(active) else None
    last = int(active[-1]) if len(active) else None
    if first is None or float(np.max(absolute)) < 1e-3:
        raise RuntimeError("instrument render is silent")
    if cc64_ratio < 2.0:
        raise RuntimeError(f"CC64 response was not distinguishable: ratio={cc64_ratio}")

    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".wav", dir=output.parent)
    os.close(fd)
    os.unlink(temporary_name)
    temporary = Path(temporary_name)
    try:
        with AudioFile(str(temporary), "w", args.sample_rate, 2, bit_depth=32) as target:
            target.write(sustained)
        audio_hash = sha256(temporary.read_bytes())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)

    parameter_metadata = {
        key: {"name": value.name, "raw_value": value.raw_value, "description": str(value)}
        for key, value in instrument.parameters.items()
    }
    report = {
        "schema_version": 1,
        "backend": {"pedalboard": pedalboard.__version__, "python": platform.python_version()},
        "plugin": {
            "name": instrument.name,
            "path": str(plugin_path),
            "binary_sha256": plugin_binary_hash,
            "is_instrument": instrument.is_instrument,
            "parameter_count": len(instrument.parameters),
            "parameters": parameter_metadata,
        },
        "state": {"path": str(state_path), "sha256": state_hash, "restored_existing": restored},
        "midi": {"note_on_off": "honoured", "cc64_sustain": "honoured", "cc64_energy_ratio": cc64_ratio},
        "audio": {
            "path": str(output), "sha256": audio_hash, "sample_rate": args.sample_rate,
            "channels": sustained.shape[0], "frames": sustained.shape[1], "duration_s": duration,
            "format": "WAV float32", "peak": float(np.max(absolute)),
            "rms": float(np.sqrt(np.mean(np.square(sustained, dtype=np.float64)))),
            "first_active_sample": first, "latency_from_note_on_samples": first - round(0.25 * args.sample_rate),
            "last_active_sample": last, "tail_after_cc64_off_s": max(0.0, last / args.sample_rate - 1.25),
        },
        "elapsed_s": time.monotonic() - started,
        "device_mode": "offline plugin process; no audio stream/device opened",
    }
    atomic_bytes(output.with_suffix(output.suffix + ".json"), (json.dumps(report, indent=2, sort_keys=True) + "\n").encode())
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
