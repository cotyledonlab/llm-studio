#!/usr/bin/env python3
"""Run a bounded, headless SuperCollider NRT phrase qualification.

Dependencies: Python 3.10+, supriya 26, numpy.  This invokes ``scsynth -N``;
it never boots a realtime server or opens an audio device.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
import supriya
from supriya import SynthDefBuilder
from supriya.scsynth import Options


PROBE_VERSION = "1"


def synthdef(state: dict):
    ug = supriya.ugens
    with SynthDefBuilder(
        frequency=440.0,
        amplitude=float(state["amplitude"]),
        attack=float(state["attack_s"]),
        release=float(state["release_s"]),
        out=0,
    ) as builder:
        trigger = ug.Trig.kr(source=1.0, duration=0.001)
        envelope = ug.EnvGen.kr(
            gate=trigger,
            envelope=supriya.Envelope.percussive(
                attack_time=builder["attack"],
                release_time=builder["release"],
            ),
            done_action=2,
        )
        signal = ug.SinOsc.ar(frequency=builder["frequency"])
        signal = signal * envelope * builder["amplitude"]
        ug.Out.ar(bus=builder["out"], source=[signal, signal])
        return builder.build("llm_studio_qualified_sine_phrase")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def wav_measurements(path: Path, declared_start_s: float, musical_end_s: float) -> dict:
    with wave.open(str(path), "rb") as source:
        channels = source.getnchannels()
        rate = source.getframerate()
        width = source.getsampwidth()
        frames = source.getnframes()
        if width != 2:
            raise RuntimeError(f"expected PCM16 evidence WAV, got {width * 8}-bit")
        samples = np.frombuffer(source.readframes(frames), dtype="<i2").reshape(-1, channels)
    mono = np.max(np.abs(samples.astype(np.float64) / 32768.0), axis=1)
    threshold = 1e-4
    active = np.flatnonzero(mono > threshold)
    first = int(active[0]) if len(active) else None
    last = int(active[-1]) if len(active) else None
    expected_start = round(declared_start_s * rate)
    return {
        "sample_rate": rate,
        "channels": channels,
        "sample_width_bits": width * 8,
        "frames": frames,
        "duration_s": frames / rate,
        "peak": float(mono.max(initial=0.0)),
        "rms": float(np.sqrt(np.mean(np.square(samples.astype(np.float64) / 32768.0)))),
        "declared_start_silence_s": declared_start_s,
        "measured_first_active_sample": first,
        "start_offset_samples": None if first is None else first - expected_start,
        "measured_last_active_sample": last,
        "measured_release_past_musical_end_s": None if last is None else max(0.0, last / rate - musical_end_s),
    }


def run(job_path: Path) -> dict:
    job = json.loads(job_path.read_text())
    required = {"job_id", "seed", "sample_rate", "start_s", "duration_s", "tail_s", "instrument", "performance", "output"}
    missing = required - job.keys()
    if missing:
        raise ValueError(f"missing job fields: {sorted(missing)}")
    if job["instrument"]["id"] != "qualified-sine-v1":
        raise ValueError("this qualification probe only accepts instrument id qualified-sine-v1")

    output = Path(job["output"]).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    definition = synthdef(job["instrument"]["state"])
    compiled = definition.compile()
    score = supriya.Score()
    with score.at(0.0):
        score.add_synthdefs(definition)
    for event in job["performance"]:
        at = float(job["start_s"]) + float(event["at_s"])
        with score.at(at):
            score.add_synth(
                definition,
                frequency=float(event["frequency_hz"]),
                amplitude=float(event.get("amplitude", job["instrument"]["state"]["amplitude"])),
                attack=float(job["instrument"]["state"]["attack_s"]),
                release=float(event.get("release_s", job["instrument"]["state"]["release_s"])),
            )

    render_duration = float(job["start_s"]) + float(job["duration_s"]) + float(job["tail_s"])
    fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".wav", dir=output.parent)
    os.close(fd)
    os.unlink(temporary_name)
    temporary = Path(temporary_name)
    started = time.monotonic()
    try:
        rendered, return_code = supriya.render(
            score,
            output_file_path=temporary,
            header_format="WAV",
            sample_format="INT16",
            sample_rate=int(job["sample_rate"]),
            duration=render_duration,
            options=Options(
                output_bus_channel_count=2,
            ),
        )
        if return_code or not temporary.exists() or temporary.stat().st_size <= 44:
            raise RuntimeError(f"scsynth NRT failed: returncode={return_code}, output={rendered}")
        measurements = wav_measurements(
            temporary,
            float(job["start_s"]),
            float(job["start_s"]) + float(job["duration_s"]),
        )
        audio_hash = digest(temporary.read_bytes())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)

    scsynth_version = subprocess.run(
        ["scsynth", "-v"], check=False, capture_output=True, text=True
    ).stdout.strip()
    canonical_job = json.dumps(job, sort_keys=True, separators=(",", ":")).encode()
    manifest = {
        "schema_version": 1,
        "probe_version": PROBE_VERSION,
        "job_id": job["job_id"],
        "seed": job["seed"],
        "job_sha256": digest(canonical_job),
        "instrument_state_sha256": digest(json.dumps(job["instrument"], sort_keys=True).encode()),
        "synthdef_sha256": digest(compiled),
        "audio_sha256": audio_hash,
        "output": str(output),
        "elapsed_s": time.monotonic() - started,
        "engine": {"scsynth": scsynth_version, "supriya": supriya.__version__, "python": platform.python_version()},
        "device_mode": "non-realtime scsynth -N; no live audio device",
        "measurements": measurements,
    }
    atomic_json(output.with_suffix(output.suffix + ".json"), manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.job), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
