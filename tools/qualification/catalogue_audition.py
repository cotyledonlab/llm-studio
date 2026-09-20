#!/usr/bin/env python3
"""Render one packaged catalogue audition without opening an audio device."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
import platform
import resource
import shutil
import struct
import sys
import tempfile
import time
from pathlib import Path

from llm_studio.catalogue import Catalogue, Instrument, plain
from llm_studio.render_jobs import RenderJob


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_manifest(path: Path, value: dict) -> None:
    with path.open("w") as stream:
        json.dump(value, stream, allow_nan=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _rename_no_replace(source: Path, destination: Path) -> None:
    """Atomically rename a directory while refusing an existing destination."""

    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if sys.platform == "darwin":
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        arguments = (source_bytes, destination_bytes, 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        rename = libc.renameat2
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        arguments = (-100, source_bytes, -100, destination_bytes, 0x00000001)
    else:
        raise OSError(
            errno.ENOTSUP,
            f"atomic no-replace publication is unsupported on {sys.platform}",
        )
    rename.restype = ctypes.c_int
    ctypes.set_errno(0)
    if rename(*arguments) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))


def midi_schedule(fixture: dict) -> list[tuple[bytes, float]]:
    """Convert declarative note/controller events to one timestamped MIDI schedule."""

    schedule: list[tuple[bytes, float]] = []
    start = float(fixture["start_s"])
    for event in fixture["events"]:
        at = start + float(event["at_s"])
        if "midi_note" in event:
            note = int(event["midi_note"])
            velocity = int(event["velocity"])
            schedule.append((bytes([0x90, note, velocity]), at))
            schedule.append((bytes([0x80, note, 0]), at + float(event["duration_s"])))
        else:
            schedule.append((bytes([0xB0, int(event["controller"]), int(event["value"])]), at))
    return sorted(schedule, key=lambda item: item[1])


def validate_performance(instrument: Instrument) -> None:
    low = int(instrument.data["playable_range"]["midi_min"])
    high = int(instrument.data["playable_range"]["midi_max"])
    controllers = instrument.data["mappings"]["controllers"]
    drum_map = instrument.data["mappings"]["drum_map"]
    for event in instrument.fixture["events"]:
        if "midi_note" in event:
            note = int(event["midi_note"])
            if not low <= note <= high:
                raise ValueError(f"MIDI note {note} is outside {instrument.id} range {low}..{high}")
            if drum_map and str(note) not in drum_map:
                raise ValueError(f"MIDI note {note} has no drum mapping for {instrument.id}")
        elif str(event["controller"]) not in controllers:
            raise ValueError(f"CC{event['controller']} is not declared for {instrument.id}")


def measurements(audio, sample_rate: int, start_s: float, musical_end_s: float) -> dict:
    import numpy as np

    absolute = np.max(np.abs(audio), axis=0)
    active = np.flatnonzero(absolute > 1e-5)
    first = int(active[0]) if len(active) else None
    last = int(active[-1]) if len(active) else None
    return {
        "sample_rate": sample_rate,
        "channels": int(audio.shape[0]),
        "frames": int(audio.shape[1]),
        "sample_sha256": digest(np.asarray(audio, dtype="<f4").tobytes(order="C")),
        "duration_s": audio.shape[1] / sample_rate,
        "peak": float(np.max(absolute)),
        "rms": float(np.sqrt(np.mean(np.square(audio, dtype=np.float64)))),
        "first_active_sample": first,
        "start_offset_samples": None if first is None else first - round(start_s * sample_rate),
        "last_active_sample": last,
        "tail_after_musical_end_s": None if last is None else max(0.0, last / sample_rate - musical_end_s),
    }


def read_float_wav(path: Path):
    """Read the uncompressed stereo float WAV emitted by scsynth NRT."""

    import numpy as np

    data = path.read_bytes()
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise RuntimeError("scsynth output is not a RIFF/WAVE file")
    declared_size = struct.unpack_from("<I", data, 4)[0] + 8
    if declared_size != len(data):
        raise RuntimeError(
            f"scsynth WAV RIFF size is {declared_size} bytes; file is {len(data)} bytes"
        )
    offset = 12
    format_info = None
    samples = None
    while offset + 8 <= len(data):
        name = data[offset:offset + 4]
        size = struct.unpack_from("<I", data, offset + 4)[0]
        body_start = offset + 8
        body_end = body_start + size
        padded_end = body_end + (size % 2)
        if padded_end > len(data):
            raise RuntimeError(f"scsynth WAV chunk {name!r} extends past end of file")
        body = data[body_start:body_end]
        if name == b"fmt ":
            if format_info is not None or size < 16:
                raise RuntimeError("scsynth WAV has invalid fmt chunk")
            format_info = struct.unpack_from("<HHIIHH", body)
        elif name == b"data":
            if samples is not None:
                raise RuntimeError("scsynth WAV has multiple data chunks")
            samples = body
        offset = padded_end
    if offset != len(data):
        raise RuntimeError("scsynth WAV has an incomplete trailing chunk")
    if format_info is None or samples is None:
        raise RuntimeError("scsynth WAV lacks fmt or data chunk")
    audio_format, channels, rate, byte_rate, block_align, bits = format_info
    if audio_format != 3 or bits != 32 or channels != 2:
        raise RuntimeError(f"expected stereo float32 WAV, got format={audio_format}, channels={channels}, bits={bits}")
    expected_align = channels * bits // 8
    if block_align != expected_align or byte_rate != rate * expected_align:
        raise RuntimeError("scsynth WAV has inconsistent format alignment")
    if len(samples) % block_align:
        raise RuntimeError("scsynth WAV data contains an incomplete sample frame")
    audio = np.frombuffer(samples, dtype="<f4").reshape(-1, channels).T.copy()
    return audio, rate


def validate_audio(audio, sample_rate: int, fixture: dict, *, block_size: int = 0) -> None:
    import numpy as np

    expected_rate = int(fixture["sample_rate"])
    if sample_rate != expected_rate:
        raise RuntimeError(f"render sample rate is {sample_rate}; expected {expected_rate}")
    if audio.ndim != 2 or audio.shape[0] != 2:
        raise RuntimeError(f"render shape is {audio.shape}; expected stereo")
    if not np.isfinite(audio).all():
        raise RuntimeError("render contains non-finite samples")
    expected_frames = round(
        (float(fixture["start_s"]) + float(fixture["duration_s"]) + float(fixture["tail_s"]))
        * expected_rate
    )
    padding = audio.shape[1] - expected_frames
    if padding < 0 or padding > block_size:
        raise RuntimeError(
            f"render has {audio.shape[1]} frames; expected {expected_frames}"
            + (f" plus at most {block_size} frames of block padding" if block_size else "")
        )
    peak = float(np.max(np.abs(audio)))
    if peak <= 1e-5:
        raise RuntimeError("render is silent")
    if peak > 1.0:
        raise RuntimeError(f"render clips with peak {peak}")


def sc_definitions(instrument: Instrument):
    import supriya
    from supriya import SynthDefBuilder
    from supriya.enums import DoneAction

    ug = supriya.ugens
    state = instrument.data["state"]
    params = state["parameters"]
    definitions = {}
    if instrument.data["role"] == "bass":
        with SynthDefBuilder(frequency=55.0, amplitude=params["level"], duration=0.5, out=0) as builder:
            envelope = ug.EnvGen.kr(
                envelope=supriya.Envelope.linen(
                    attack_time=params["attack_s"],
                    sustain_time=builder["duration"],
                    release_time=params["release_s"],
                ),
                done_action=DoneAction.FREE_SYNTH,
            )
            source = ug.Pulse.ar(frequency=builder["frequency"], width=params["pulse_width"])
            source = ug.LPF.ar(source=source, frequency=builder["frequency"] * 6)
            source = source * envelope * builder["amplitude"]
            ug.Out.ar(bus=builder["out"], source=[source, source])
            definitions["bass"] = builder.build(state["synthdef"])
    else:
        for name, decay, make_source in (
            ("kick", params["kick_decay_s"], lambda: ug.SinOsc.ar(frequency=ug.XLine.kr(start=120, stop=45, duration=0.05))),
            ("snare", params["snare_decay_s"], lambda: ug.BPF.ar(source=ug.WhiteNoise.ar(), frequency=1800, reciprocal_of_q=1.2)),
            ("closed_hat", params["hat_decay_s"], lambda: ug.HPF.ar(source=ug.WhiteNoise.ar(), frequency=6500)),
        ):
            with SynthDefBuilder(amplitude=params["level"], seed=state["seed"], out=0) as builder:
                ug.RandSeed.kr(trigger=1, seed=builder["seed"])
                envelope = ug.EnvGen.kr(
                    envelope=supriya.Envelope.percussive(attack_time=0.001, release_time=decay),
                    done_action=DoneAction.FREE_SYNTH,
                )
                source = make_source() * envelope * builder["amplitude"]
                ug.Out.ar(bus=builder["out"], source=[source, source])
                definitions[name] = builder.build(f"{state['synthdef']}_{name}")
    return definitions


def render_supercollider(instrument: Instrument, output: Path) -> tuple[dict, dict]:
    import supriya
    from supriya.scsynth import Options

    fixture = instrument.fixture
    definitions = sc_definitions(instrument)
    observed_definition_hashes = {
        name: digest(definition.compile()) for name, definition in definitions.items()
    }
    expected_definition_hashes = plain(instrument.data["state"]["synthdef_sha256"])
    if observed_definition_hashes != expected_definition_hashes:
        raise RuntimeError(
            f"{instrument.id} SynthDef integrity check failed: expected "
            f"{expected_definition_hashes}, found {observed_definition_hashes}"
        )
    score = supriya.Score()
    with score.at(0):
        score.add_synthdefs(*definitions.values())
    drum_map = instrument.data["mappings"]["drum_map"]
    for index, event in enumerate(fixture["events"]):
        at = float(fixture["start_s"]) + float(event["at_s"])
        with score.at(at):
            if drum_map:
                definition = definitions[drum_map[str(event["midi_note"])]]
                score.add_synth(
                    definition,
                    amplitude=instrument.data["state"]["parameters"]["level"] * int(event["velocity"]) / 127,
                    seed=int(instrument.data["state"]["seed"]) + index,
                )
            else:
                definition = definitions["bass"]
                frequency=440.0 * (2.0 ** ((int(event["midi_note"]) - 69) / 12.0))
                score.add_synth(
                    definition,
                    frequency=frequency,
                    amplitude=instrument.data["state"]["parameters"]["level"] * int(event["velocity"]) / 127,
                    duration=float(event["duration_s"]),
                )
    duration = float(fixture["start_s"]) + float(fixture["duration_s"]) + float(fixture["tail_s"])
    rendered, return_code = supriya.render(
        score,
        output_file_path=output,
        header_format="WAV",
        sample_format="FLOAT",
        sample_rate=int(fixture["sample_rate"]),
        duration=duration,
        options=Options(
            executable=instrument.runtime["executable"],
            output_bus_channel_count=2,
        ),
    )
    if return_code or not output.exists():
        raise RuntimeError(f"scsynth NRT failed: returncode={return_code}, output={rendered}")
    audio, rate = read_float_wav(output)
    validate_audio(audio, rate, fixture, block_size=64)
    engine = {
        "scsynth": instrument.runtime["executable_version"],
        "scsynth_path": instrument.runtime["executable"],
        "supriya": supriya.__version__,
        "synthdef_sha256": observed_definition_hashes,
    }
    return measurements(audio, rate, float(fixture["start_s"]), float(fixture["start_s"]) + float(fixture["duration_s"])), engine


def render_pedalboard(instrument: Instrument, output: Path) -> tuple[dict, dict]:
    import pedalboard
    from pedalboard import load_plugin
    from pedalboard.io import AudioFile

    plugin_path = Path(instrument.runtime["assets"][0])
    bundle = plugin_path.parents[2]
    plugin = load_plugin(str(bundle), initialization_timeout=20.0)
    restored_state = instrument.restored_state()
    expected_state = instrument.data["state"]["raw_state_sha256"]
    plugin.raw_state = restored_state
    observed_state = digest(plugin.raw_state)
    if observed_state != expected_state:
        raise RuntimeError(
            f"Dexed state restore requires SHA-256 {expected_state}; found {observed_state}"
        )
    fixture = instrument.fixture
    duration = float(fixture["start_s"]) + float(fixture["duration_s"]) + float(fixture["tail_s"])
    audio = plugin.process(
        midi_schedule(dict(fixture)),
        duration=duration,
        sample_rate=int(fixture["sample_rate"]),
        num_channels=2,
        buffer_size=512,
        reset=True,
    )
    validate_audio(audio, fixture["sample_rate"], fixture)
    with AudioFile(str(output), "w", fixture["sample_rate"], 2, bit_depth=32) as target:
        target.write(audio)
    engine = {"pedalboard": pedalboard.__version__, "plugin": plugin.name}
    return measurements(audio, fixture["sample_rate"], fixture["start_s"], fixture["start_s"] + fixture["duration_s"]), engine


def render(
    instrument_id: str,
    result: Path,
    *,
    published_result: Path | None = None,
) -> dict:
    catalogue = Catalogue.packaged()
    instrument = catalogue.check_dependencies(instrument_id)
    validate_performance(instrument)
    result = result.expanduser().resolve()
    logical_result = (
        result
        if published_result is None
        else published_result.expanduser().resolve()
    )
    result.parent.mkdir(parents=True, exist_ok=True)
    if result.exists():
        raise FileExistsError(f"immutable audition result already exists: {result}")
    staging = Path(tempfile.mkdtemp(prefix=f".{result.name}.", dir=result.parent))
    published = False
    audio_path = staging / "audio.wav"
    started = time.monotonic()
    self_before = resource.getrusage(resource.RUSAGE_SELF)
    children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        if instrument.data["backend"]["name"] == "SuperCollider NRT":
            observed, engine = render_supercollider(instrument, audio_path)
        else:
            observed, engine = render_pedalboard(instrument, audio_path)
        audio_hash = digest(audio_path.read_bytes())
        with audio_path.open("rb+") as stream:
            os.fsync(stream.fileno())
        self_after = resource.getrusage(resource.RUSAGE_SELF)
        children_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu_s = (
            self_after.ru_utime - self_before.ru_utime
            + self_after.ru_stime - self_before.ru_stime
            + children_after.ru_utime - children_before.ru_utime
            + children_after.ru_stime - children_before.ru_stime
        )
        peak_rss = max(self_after.ru_maxrss, children_after.ru_maxrss)
        manifest = {
            "schema_version": 1,
            "instrument_id": instrument.id,
            "state_sha256": instrument.data["state_sha256"],
            "fixture_sha256": instrument.data["audition_fixture_sha256"],
            "audio_sha256": audio_hash,
            "backend": plain(instrument.data["backend"]),
            "assets": [
                {"name": asset["name"], "sha256": asset["sha256"]}
                for asset in instrument.data["assets"]
            ],
            "audio": {
                "path": str(logical_result / "audio.wav"),
                "format": "WAV float32",
                **observed,
            },
            "engine": {**engine, "python": platform.python_version()},
            "elapsed_s": time.monotonic() - started,
            "resources": {
                "cpu_s": cpu_s,
                "peak_rss": peak_rss,
                "peak_rss_unit": "bytes" if platform.system() == "Darwin" else "KiB",
            },
            "device_mode": "offline render; no audio stream/device opened",
        }
        _write_manifest(staging / "manifest.json", manifest)
        _fsync_directory(staging)
        try:
            _rename_no_replace(staging, result)
        except OSError as exc:
            if result.exists() or result.is_symlink():
                raise FileExistsError(
                    f"immutable audition result already exists: {result}"
                ) from exc
            raise
        published = True
        _fsync_directory(result.parent)
        return manifest
    finally:
        if not published and staging.exists():
            shutil.rmtree(staging)


def render_job(job: RenderJob, output: Path) -> None:
    """Render a catalogue audition for parent-owned job publication."""

    instrument_id = job.payload.get("instrument_id")
    if not isinstance(instrument_id, str) or not instrument_id:
        raise ValueError("catalogue render job payload requires instrument_id")
    render(
        instrument_id,
        output,
        published_result=job.result_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("instrument_id")
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(render(args.instrument_id, args.result), allow_nan=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
