#!/usr/bin/env python3
"""Render one packaged catalogue audition without opening an audio device."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import struct
import tempfile
import time
from pathlib import Path

from llm_studio.catalogue import Catalogue, Instrument


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
        Path(temporary).unlink(missing_ok=True)
        raise


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
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise RuntimeError("scsynth output is not a RIFF/WAVE file")
    offset = 12
    format_info = None
    samples = None
    while offset + 8 <= len(data):
        name = data[offset:offset + 4]
        size = struct.unpack_from("<I", data, offset + 4)[0]
        body = data[offset + 8:offset + 8 + size]
        if name == b"fmt ":
            format_info = struct.unpack_from("<HHIIHH", body)
        elif name == b"data":
            samples = body
        offset += 8 + size + (size % 2)
    if format_info is None or samples is None:
        raise RuntimeError("scsynth WAV lacks fmt or data chunk")
    audio_format, channels, rate, _, _, bits = format_info
    if audio_format != 3 or bits != 32 or channels != 2:
        raise RuntimeError(f"expected stereo float32 WAV, got format={audio_format}, channels={channels}, bits={bits}")
    audio = np.frombuffer(samples, dtype="<f4").reshape(-1, channels).T.copy()
    return audio, rate


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
        options=Options(output_bus_channel_count=2),
    )
    if return_code or not output.exists():
        raise RuntimeError(f"scsynth NRT failed: returncode={return_code}, output={rendered}")
    audio, rate = read_float_wav(output)
    engine = {
        "scsynth": instrument.data["backend"]["version"],
        "supriya": supriya.__version__,
        "synthdef_sha256": {
            name: digest(definition.compile()) for name, definition in definitions.items()
        },
    }
    return measurements(audio, rate, float(fixture["start_s"]), float(fixture["start_s"]) + float(fixture["duration_s"])), engine


def render_pedalboard(instrument: Instrument, output: Path) -> tuple[dict, dict]:
    import numpy as np
    import pedalboard
    from pedalboard import load_plugin
    from pedalboard.io import AudioFile

    asset = instrument.data["assets"][0]
    plugin_path = Path(str(asset["path"]).replace("$HOME", str(Path.home())))
    bundle = plugin_path.parents[2]
    plugin = load_plugin(str(bundle), initialization_timeout=20.0)
    observed_state = digest(plugin.raw_state)
    expected_state = instrument.data["state"]["raw_state_sha256"]
    if observed_state != expected_state:
        raise RuntimeError(f"Dexed factory state requires SHA-256 {expected_state}; found {observed_state}")
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
    if not np.isfinite(audio).all() or audio.shape != (2, round(duration * fixture["sample_rate"])):
        raise RuntimeError(f"invalid Pedalboard render shape/content: {audio.shape}")
    with AudioFile(str(output), "w", fixture["sample_rate"], 2, bit_depth=32) as target:
        target.write(audio)
    engine = {"pedalboard": pedalboard.__version__, "plugin": plugin.name}
    return measurements(audio, fixture["sample_rate"], fixture["start_s"], fixture["start_s"] + fixture["duration_s"]), engine


def render(instrument_id: str, output: Path) -> dict:
    catalogue = Catalogue.packaged()
    instrument = catalogue.check_dependencies(instrument_id)
    validate_performance(instrument)
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".wav", dir=output.parent)
    os.close(fd)
    Path(temporary_name).unlink()
    temporary = Path(temporary_name)
    started = time.monotonic()
    self_before = resource.getrusage(resource.RUSAGE_SELF)
    children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        if instrument.data["backend"]["name"] == "SuperCollider NRT":
            observed, engine = render_supercollider(instrument, temporary)
        else:
            observed, engine = render_pedalboard(instrument, temporary)
        audio_hash = digest(temporary.read_bytes())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
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
        "backend": instrument.data["backend"],
        "assets": [
            {"name": asset["name"], "sha256": asset["sha256"]}
            for asset in instrument.data["assets"]
        ],
        "audio": {"path": str(output), "format": "WAV float32", **observed},
        "engine": {**engine, "python": platform.python_version()},
        "elapsed_s": time.monotonic() - started,
        "resources": {
            "cpu_s": cpu_s,
            "peak_rss": peak_rss,
            "peak_rss_unit": "bytes" if platform.system() == "Darwin" else "KiB",
        },
        "device_mode": "offline render; no audio stream/device opened",
    }
    atomic_json(output.with_suffix(output.suffix + ".json"), manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("instrument_id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(render(args.instrument_id, args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
