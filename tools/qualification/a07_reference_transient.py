#!/usr/bin/env python3
"""Measure SuperCollider NRT score scheduling against sample-accurate markers.

The calibration SynthDef emits an immediate impulse, a one-sample delayed copy,
and an immediate DC marker. The DC onset independently identifies the first
sample the SynthDef executes; comparing it to the impulse separates score/block
scheduling from UGen signal delay. It uses the real pinned scsynth NRT engine
without opening a realtime server or audio device.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import struct
import subprocess
import time
from pathlib import Path

import numpy as np
import supriya
from supriya import SynthDefBuilder
from supriya.scsynth import Options

from llm_studio.stem_alignment import Stem, align_stems


def _reference_synthdef():
    ug = supriya.ugens
    with SynthDefBuilder(out=0) as builder:
        impulse = ug.Impulse.ar(frequency=0.0, phase=1.0)
        delayed = ug.Delay1.ar(source=impulse)
        marker_gate = ug.Line.kr(
            start=1.0,
            stop=0.0,
            duration=0.01,
            done_action=2,
        )
        execution_marker = ug.DC.ar(source=1.0) * marker_gate
        ug.Out.ar(
            bus=builder["out"],
            source=[impulse, delayed, execution_marker],
        )
        return builder.build("llm_studio_a07_reference_transient")


def _read_float_wav(path: Path) -> tuple[np.ndarray, int]:
    data = path.read_bytes()
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise RuntimeError("scsynth output is not a RIFF/WAVE file")
    if struct.unpack_from("<I", data, 4)[0] + 8 != len(data):
        raise RuntimeError("WAV RIFF size does not match file size")
    offset = 12
    fmt = None
    payload = None
    while offset + 8 <= len(data):
        name = data[offset : offset + 4]
        size = struct.unpack_from("<I", data, offset + 4)[0]
        start = offset + 8
        end = start + size
        padded_end = end + (size % 2)
        if padded_end > len(data):
            raise RuntimeError("WAV chunk extends beyond file size")
        if name == b"fmt ":
            fmt = struct.unpack_from("<HHIIHH", data, start)
        elif name == b"data":
            payload = data[start:end]
        offset = padded_end
    if fmt is None or payload is None:
        raise RuntimeError("WAV is missing fmt or data chunk")
    encoding, channels, rate, _, block_align, bits = fmt
    if (encoding, channels, bits, block_align) != (3, 3, 32, 12):
        raise RuntimeError(f"expected 3-channel float32 WAV, got fmt={fmt}")
    if len(payload) % block_align:
        raise RuntimeError("WAV has an incomplete sample frame")
    return np.frombuffer(payload, dtype="<f4").reshape(-1, channels).copy(), rate


def _render_rate(rate: int, event_times_s: tuple[float, ...], block_size: int, output_dir: Path) -> dict:
    definition = _reference_synthdef()
    score = supriya.Score()
    with score.at(0.0):
        score.add_synthdefs(definition)
    for event_time in event_times_s:
        with score.at(event_time):
            score.add_synth(definition)

    wav_path = output_dir / f"sc-reference-{rate}.wav"
    started = time.monotonic()
    _, return_code = supriya.render(
        score,
        output_file_path=wav_path,
        header_format="WAV",
        sample_format="FLOAT",
        sample_rate=rate,
        duration=2.0,
        options=Options(
            block_size=block_size,
            output_bus_channel_count=3,
            sample_rate=rate,
        ),
    )
    elapsed = time.monotonic() - started
    if return_code != 0 or not wav_path.is_file():
        raise RuntimeError(f"scsynth NRT failed at {rate} Hz (exit={return_code})")
    audio, actual_rate = _read_float_wav(wav_path)
    if actual_rate != rate:
        raise RuntimeError(f"rendered at {actual_rate} Hz, expected {rate} Hz")

    events = []
    for event_time in event_times_s:
        expected = round(event_time * rate)
        window = max(0, expected - block_size * 2)
        stop = min(len(audio), expected + block_size * 2)
        markers = []
        for channel in range(3):
            active = np.flatnonzero(audio[window:stop, channel] != 0.0)
            markers.append(None if not len(active) else int(window + active[0]))
        impulse_frame, delayed_frame, execution_frame = markers
        if impulse_frame is None or delayed_frame is None or execution_frame is None:
            raise RuntimeError(f"missing reference marker near event {event_time}s: {markers}")
        if impulse_frame != execution_frame:
            raise RuntimeError(
                f"impulse and execution marker differ at {event_time}s: {markers}"
            )
        if delayed_frame != impulse_frame + 1:
            raise RuntimeError(
                f"Delay1 marker was not exactly one frame later at {event_time}s: {markers}"
            )
        events.append(
            {
                "declared_event_s": event_time,
                "declared_event_frame": expected,
                "decoded_wav_impulse_frame": impulse_frame,
                "decoded_wav_delay1_frame": delayed_frame,
                "decoded_wav_execution_marker_frame": execution_frame,
                "score_schedule_offset_samples": impulse_frame - expected,
                "instrument_signal_offset_samples": impulse_frame - execution_frame,
                "delay1_increment_samples": delayed_frame - impulse_frame,
            }
        )
    return {
        "sample_rate": rate,
        "channels": 3,
        "encoding": "IEEE float32 little endian",
        "block_size": block_size,
        "frames": len(audio),
        "duration_s": len(audio) / rate,
        "decoded_samples_sha256": hashlib.sha256(audio.tobytes(order="C")).hexdigest(),
        "elapsed_s": elapsed,
        "events": events,
    }


def _align_decoded_transients(
    output_dir: Path,
    measurements: list[dict],
    *,
    alignment_rate: int,
    preroll: int,
    postroll: int,
) -> dict:
    stems = []
    event_metadata = []
    for measurement in measurements:
        rate = measurement["sample_rate"]
        audio, _ = _read_float_wav(output_dir / f"sc-reference-{rate}.wav")
        for event in measurement["events"]:
            event_frame = event["decoded_wav_impulse_frame"]
            clip_start = event_frame - preroll
            clip_end = event_frame + postroll
            if clip_start < 0 or clip_end > len(audio):
                raise RuntimeError("reference clip lacks requested pre-roll/post-roll")
            clip = tuple(float(sample) for sample in audio[clip_start:clip_end, 0])
            if clip[preroll] != 1.0 or any(sample != 0.0 for sample in clip[:preroll]):
                raise RuntimeError("decoded reference impulse is not at the expected clip frame")
            stems.append(Stem((clip,), rate, event["declared_event_s"], preroll))
            event_metadata.append(
                {
                    "source_rate": rate,
                    "declared_event_s": event["declared_event_s"],
                    "source_event_frame": event_frame,
                    "source_clip_start_frame": clip_start,
                    "measured_event_offset_within_clip_samples": preroll,
                }
            )

    aligned = align_stems(tuple(stems), sample_rate=alignment_rate)
    readbacks = []
    for metadata, stem in zip(event_metadata, aligned):
        channel = np.asarray(stem.channels[0], dtype=np.float64)
        target = stem.common_reference_frame
        left = max(0, target - 2)
        right = min(len(channel), target + 3)
        peak_frame = left + int(np.argmax(np.abs(channel[left:right])))
        error = peak_frame - target
        if abs(error) > 1:
            raise RuntimeError(
                f"aligned {metadata['source_rate']} Hz transient missed target by {error} samples"
            )
        readbacks.append(
            {
                **metadata,
                "aligned_rate": stem.sample_rate,
                "common_reference_frame": target,
                "aligned_peak_frame": peak_frame,
                "alignment_error_samples": error,
                "placement_frame": stem.placement_frame,
            }
        )
    return {
        "sample_rate": alignment_rate,
        "normalization": "none",
        "channel_policy": "mono source preserved as mono",
        "readbacks": readbacks,
        "all_within_one_sample": True,
    }


def run(output_dir: Path, fixture_path: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    fixture_bytes = fixture_path.read_bytes()
    fixture = json.loads(fixture_bytes)
    event_times = tuple(float(value) for value in fixture["event_times_s"])
    block_size = int(fixture["block_size"])
    sample_rates = tuple(int(value) for value in fixture["sample_rates"])
    alignment_rate = int(fixture["alignment_sample_rate"])
    preroll = int(fixture["reference_clip_preroll_frames"])
    postroll = int(fixture["reference_clip_postroll_frames"])
    if not event_times or not sample_rates or block_size <= 0 or min(preroll, postroll) <= 0:
        raise ValueError("fixture has an empty event/rate list or invalid block/clip size")
    version = subprocess.run(
        ["scsynth", "-v"], capture_output=True, check=False, text=True
    )
    if version.returncode:
        raise RuntimeError(f"scsynth -v failed: {version.stderr.strip()}")
    measurements = [
        _render_rate(rate, event_times, block_size, output_dir)
        for rate in sample_rates
    ]
    result = {
        "schema_version": 1,
        "qualification": "A07 SuperCollider NRT reference transient",
        "engine": {
            "scsynth": version.stdout.strip(),
            "supriya": supriya.__version__,
            "python": platform.python_version(),
        },
        "device_mode": "non-realtime scsynth -N; no live server or audio device",
        "synthdef": "Impulse + Delay1 + DC execution marker",
        "marker_method": "first exactly nonzero IEEE-float frame in decoded WAV channels",
        "fixture": {
            "path": str(fixture_path),
            "sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        },
        "measurements": measurements,
        "alignment_check": _align_decoded_transients(
            output_dir,
            measurements,
            alignment_rate=alignment_rate,
            preroll=preroll,
            postroll=postroll,
        ),
    }
    (output_dir / "a07-reference-transient.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path(__file__).parent / "fixtures" / "a07-reference-transient.json",
    )
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir, args.fixture), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
