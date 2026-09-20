from __future__ import annotations

import struct
from pathlib import Path

import pytest

from llm_studio.catalogue import Catalogue
from tools.qualification import catalogue_audition as audition
from tools.qualification.catalogue_audition import (
    midi_schedule,
    read_float_wav,
    sc_definitions,
    validate_audio,
    validate_performance,
)


def test_keys_fixture_becomes_complete_timestamped_midi_schedule() -> None:
    fixture = dict(Catalogue.packaged().get("studio.keys.dexed-factory-v1").fixture)

    schedule = midi_schedule(fixture)

    assert schedule == [
        (bytes([0x90, 60, 88]), 0.25),
        (bytes([0x90, 64, 84]), 0.25),
        (bytes([0x90, 67, 82]), 0.25),
        (bytes([0xB0, 64, 127]), 0.65),
        (bytes([0xB0, 64, 0]), 1.75),
        (bytes([0x80, 60, 0]), 2.25),
        (bytes([0x80, 64, 0]), 2.25),
        (bytes([0x80, 67, 0]), 2.25),
    ]


@pytest.mark.parametrize("instrument_id", Catalogue.packaged().ids())
def test_packaged_performances_use_only_declared_ranges_and_mappings(instrument_id: str) -> None:
    validate_performance(Catalogue.packaged().get(instrument_id))


def test_float_wav_reader_handles_chunk_padding(tmp_path) -> None:
    np = pytest.importorskip("numpy")
    samples = np.array([[0.25, -0.5], [0.75, -1.0]], dtype="<f4")
    fmt = struct.pack("<HHIIHH", 3, 2, 48000, 384000, 8, 32)
    odd_chunk = b"abc"
    body = (
        b"WAVE"
        + b"JUNK" + struct.pack("<I", len(odd_chunk)) + odd_chunk + b"\0"
        + b"fmt " + struct.pack("<I", len(fmt)) + fmt
        + b"data" + struct.pack("<I", samples.nbytes) + samples.tobytes()
    )
    path = tmp_path / "fixture.wav"
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)

    audio, rate = read_float_wav(path)

    assert rate == 48000
    np.testing.assert_array_equal(audio, samples.T)


def float_wav(samples, *, rate: int = 48000, data_size: int | None = None) -> bytes:
    payload = samples.tobytes()
    fmt = struct.pack("<HHIIHH", 3, 2, rate, rate * 8, 8, 32)
    body = (
        b"WAVE"
        + b"fmt " + struct.pack("<I", len(fmt)) + fmt
        + b"data" + struct.pack("<I", len(payload) if data_size is None else data_size) + payload
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body


def test_float_wav_reader_rejects_truncated_chunk(tmp_path) -> None:
    np = pytest.importorskip("numpy")
    samples = np.zeros((2, 2), dtype="<f4")
    path = tmp_path / "truncated.wav"
    path.write_bytes(float_wav(samples, data_size=samples.nbytes + 8))

    with pytest.raises(RuntimeError, match="extends past end"):
        read_float_wav(path)


def test_float_wav_reader_rejects_incomplete_frame(tmp_path) -> None:
    np = pytest.importorskip("numpy")
    payload = np.zeros(3, dtype="<f4").tobytes()
    fmt = struct.pack("<HHIIHH", 3, 2, 48000, 384000, 8, 32)
    body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", len(payload)) + payload
    path = tmp_path / "partial.wav"
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)

    with pytest.raises(RuntimeError, match="incomplete sample frame"):
        read_float_wav(path)


def test_audio_validation_rejects_wrong_rate_short_nonfinite_and_clipping() -> None:
    np = pytest.importorskip("numpy")
    fixture = {"sample_rate": 10, "start_s": 0.1, "duration_s": 0.8, "tail_s": 0.1}
    valid = np.full((2, 10), 0.25, dtype=np.float32)

    validate_audio(valid, 10, fixture)
    with pytest.raises(RuntimeError, match="expected 10"):
        validate_audio(np.pad(valid, ((0, 0), (0, 1))), 10, fixture)
    validate_audio(np.pad(valid, ((0, 0), (0, 4))), 10, fixture, block_size=4)
    with pytest.raises(RuntimeError, match="at most 4"):
        validate_audio(np.pad(valid, ((0, 0), (0, 5))), 10, fixture, block_size=4)
    with pytest.raises(RuntimeError, match="sample rate"):
        validate_audio(valid, 11, fixture)
    with pytest.raises(RuntimeError, match="expected 10"):
        validate_audio(valid[:, :-1], 10, fixture)
    invalid = valid.copy()
    invalid[0, 0] = np.nan
    with pytest.raises(RuntimeError, match="non-finite"):
        validate_audio(invalid, 10, fixture)
    with pytest.raises(RuntimeError, match="clips"):
        validate_audio(np.full((2, 10), 1.01, dtype=np.float32), 10, fixture)


def mock_instrument():
    return Catalogue.packaged().get("studio.drums.sc-basic-v1")


class MockCatalogue:
    def __init__(self, instrument) -> None:
        self.instrument = instrument

    def check_dependencies(self, instrument_id: str):
        assert instrument_id == self.instrument.id
        return self.instrument


def successful_mock_render(instrument, output: Path):
    output.write_bytes(b"mock float WAV")
    return ({"sample_rate": 48000, "channels": 2, "frames": 1}, {"mock": "1"})


def test_result_directory_is_published_as_one_immutable_unit(tmp_path, monkeypatch) -> None:
    instrument = mock_instrument()
    monkeypatch.setattr(audition.Catalogue, "packaged", lambda: MockCatalogue(instrument))
    monkeypatch.setattr(audition, "render_supercollider", successful_mock_render)
    result = tmp_path / "audition-result"

    manifest = audition.render(instrument.id, result)

    assert (result / "audio.wav").read_bytes() == b"mock float WAV"
    assert (result / "manifest.json").exists()
    assert manifest["audio"]["path"] == str(result / "audio.wav")
    with pytest.raises(FileExistsError, match="immutable audition result"):
        audition.render(instrument.id, result)
    assert (result / "audio.wav").read_bytes() == b"mock float WAV"


def test_concurrent_publisher_cannot_replace_winning_result(tmp_path, monkeypatch) -> None:
    instrument = mock_instrument()
    monkeypatch.setattr(audition.Catalogue, "packaged", lambda: MockCatalogue(instrument))
    result = tmp_path / "audition-result"

    def lose_race(instrument, output):
        output.write_bytes(b"loser")
        result.mkdir()
        (result / "audio.wav").write_bytes(b"winner")
        (result / "manifest.json").write_text('{"winner": true}\n')
        return ({"sample_rate": 48000, "channels": 2, "frames": 1}, {"mock": "1"})

    monkeypatch.setattr(audition, "render_supercollider", lose_race)

    with pytest.raises(FileExistsError, match="immutable audition result"):
        audition.render(instrument.id, result)

    assert (result / "audio.wav").read_bytes() == b"winner"
    assert not any(path.name.startswith(".audition-result.") for path in tmp_path.iterdir())


def test_publication_fsyncs_parent_after_atomic_rename(tmp_path, monkeypatch) -> None:
    instrument = mock_instrument()
    monkeypatch.setattr(audition.Catalogue, "packaged", lambda: MockCatalogue(instrument))
    monkeypatch.setattr(audition, "render_supercollider", successful_mock_render)
    events = []
    real_rename = audition._rename_no_replace

    def record_rename(*args, **kwargs):
        events.append("publish")
        return real_rename(*args, **kwargs)

    monkeypatch.setattr(audition, "_rename_no_replace", record_rename)
    monkeypatch.setattr(audition, "_fsync_directory", lambda path: events.append(path.name))
    result = tmp_path / "audition-result"

    audition.render(instrument.id, result)

    assert result.is_dir()
    assert not result.is_symlink()
    assert events[-2:] == ["publish", tmp_path.name]


def test_manifest_failure_publishes_nothing_and_cleans_staging(tmp_path, monkeypatch) -> None:
    instrument = mock_instrument()
    monkeypatch.setattr(audition.Catalogue, "packaged", lambda: MockCatalogue(instrument))
    monkeypatch.setattr(audition, "render_supercollider", successful_mock_render)
    monkeypatch.setattr(audition, "_write_manifest", lambda *args: (_ for _ in ()).throw(OSError("full")))
    result = tmp_path / "audition-result"

    with pytest.raises(OSError, match="full"):
        audition.render(instrument.id, result)

    assert not result.exists()
    assert list(tmp_path.iterdir()) == []


def test_supercollider_render_uses_validated_executable(tmp_path, monkeypatch) -> None:
    np = pytest.importorskip("numpy")
    supriya = pytest.importorskip("supriya")
    instrument = Catalogue.packaged().check_dependencies(
        "studio.bass.sc-pulse-v1",
        executables={"scsynth": Path("/validated/scsynth")},
        executable_versions={"scsynth": "scsynth 3.14.1 build 426edf6"},
        distributions={"supriya": "26.9b0"},
    )
    captured = {}

    def fake_render(score, *, output_file_path, options, **kwargs):
        captured["executable"] = options.executable
        frames = round(
            (instrument.fixture["start_s"] + instrument.fixture["duration_s"] + instrument.fixture["tail_s"])
            * instrument.fixture["sample_rate"]
        )
        samples = np.full((frames, 2), 0.1, dtype="<f4")
        output_file_path.write_bytes(float_wav(samples))
        return output_file_path, 0

    monkeypatch.setattr(supriya, "render", fake_render)

    _, engine = audition.render_supercollider(instrument, tmp_path / "audio.wav")

    assert captured["executable"] == "/validated/scsynth"
    assert engine["scsynth"] == "scsynth 3.14.1 build 426edf6"


def test_supercollider_render_rejects_definition_drift(tmp_path) -> None:
    pytest.importorskip("numpy")
    pytest.importorskip("supriya")
    instrument = Catalogue.packaged().check_dependencies(
        "studio.bass.sc-pulse-v1",
        executables={"scsynth": Path("/validated/scsynth")},
        executable_versions={"scsynth": "scsynth 3.14.1 build 426edf6"},
        distributions={"supriya": "26.9b0"},
    )
    state = dict(instrument.data["state"])
    state["synthdef_sha256"] = {"bass": "0" * 64}
    data = dict(instrument.data)
    data["state"] = state
    drifted = type(instrument)(data, instrument.fixture, instrument.runtime)

    with pytest.raises(RuntimeError, match="SynthDef integrity check failed"):
        audition.render_supercollider(drifted, tmp_path / "audio.wav")


@pytest.mark.parametrize(
    "instrument_id, expected_names",
    [
        ("studio.drums.sc-basic-v1", {"kick", "snare", "closed_hat"}),
        ("studio.bass.sc-pulse-v1", {"bass"}),
    ],
)
def test_supercollider_states_compile_to_named_synthdefs(instrument_id: str, expected_names: set[str]) -> None:
    pytest.importorskip("supriya")

    definitions = sc_definitions(Catalogue.packaged().get(instrument_id))

    assert set(definitions) == expected_names
    assert all(definition.compile() for definition in definitions.values())
