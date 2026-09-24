from __future__ import annotations

import pytest

from llm_studio.stem_alignment import Stem, align_stems


def _impulse(frames: int, at: int, amplitude: float = 1.0) -> tuple[float, ...]:
    return tuple(amplitude if index == at else 0.0 for index in range(frames))


def _peak_position(channel: tuple[float, ...]) -> int:
    return max(range(len(channel)), key=lambda index: abs(channel[index]))


def test_mixed_mono_stereo_transients_align_after_resampling_and_compensation() -> None:
    mono = Stem((_impulse(1_000, 7),), 44_100, 0.02, 7)
    stereo = Stem((_impulse(1_300, 11, 0.5), _impulse(1_300, 11, 0.25)), 48_000, 0.02, 11)
    converted = align_stems((mono, stereo))

    assert [len(stem.channels) for stem in converted] == [1, 2]
    positions = [_peak_position(stem.channels[0]) for stem in converted]
    assert abs(positions[0] - positions[1]) <= 1
    assert all(abs(position - stem.common_reference_frame) <= 1 for position, stem in zip(positions, converted))
    assert converted[1].channels[0][positions[1]] == pytest.approx(0.5)
    assert converted[1].channels[1][positions[1]] == pytest.approx(0.25)
    assert len(converted[0].channels[0]) == len(converted[1].channels[0])
    assert converted[1].channels[0][-1] == 0.0
    assert converted[1].source_frames == converted[1].converted_frames == 1_300


def test_downsampling_retains_reference_position_and_does_not_normalize() -> None:
    loud = Stem((_impulse(2_000, 19, 0.8),), 96_000, 0.01, 19)
    quiet = Stem((_impulse(1_000, 5, 0.1),), 48_000, 0.01, 5)
    aligned = align_stems((loud, quiet))

    assert abs(_peak_position(aligned[0].channels[0]) - _peak_position(aligned[1].channels[0])) <= 1
    assert max(aligned[0].channels[0]) < 0.8
    assert max(aligned[1].channels[0]) == pytest.approx(0.1)
    assert aligned[0].converted_frames == 1_000


def test_invalid_layout_and_nonfinite_audio_are_rejected() -> None:
    with pytest.raises(ValueError, match="same frame count"):
        Stem(((1.0,), (1.0, 0.0)), 48_000, 0, 0)
    with pytest.raises(ValueError, match="non-finite"):
        Stem(((float("nan"),),), 48_000, 0, 0)
