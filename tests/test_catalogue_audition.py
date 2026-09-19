from __future__ import annotations

import struct

import pytest

from llm_studio.catalogue import Catalogue
from tools.qualification.catalogue_audition import (
    midi_schedule,
    read_float_wav,
    sc_definitions,
    validate_performance,
)


def test_keys_fixture_becomes_complete_timestamped_midi_schedule() -> None:
    fixture = dict(Catalogue.packaged().get("studio.keys.dexed-factory-v1").fixture)

    schedule = midi_schedule(fixture)

    assert len(schedule) == 8
    assert schedule[0] == (bytes([0x90, 60, 88]), 0.25)
    assert (bytes([0xB0, 64, 127]), 0.65) in schedule
    assert schedule[-1] == (bytes([0xB0, 64, 0]), 1.75)


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
