"""Place isolated stems on a common sample timeline without changing their gain.

Latency values must come from a qualified transient measurement for the exact
renderer and patch. Musical onset thresholds are not such a measurement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Stem:
    channels: tuple[tuple[float, ...], ...]
    sample_rate: int
    start_s: float
    measured_latency_samples: int

    def __post_init__(self) -> None:
        if self.sample_rate <= 0 or self.start_s < 0 or self.measured_latency_samples < 0:
            raise ValueError("invalid stem timebase or latency")
        if len(self.channels) not in (1, 2) or not self.channels[0]:
            raise ValueError("stem must contain nonempty mono or stereo audio")
        if any(len(channel) != len(self.channels[0]) for channel in self.channels):
            raise ValueError("stem channels must have the same frame count")
        if any(not math.isfinite(sample) for channel in self.channels for sample in channel):
            raise ValueError("stem contains non-finite audio")


@dataclass(frozen=True)
class AlignedStem:
    channels: tuple[tuple[float, ...], ...]
    sample_rate: int
    placement_frame: int
    common_reference_frame: int
    source_frames: int
    converted_frames: int
    measured_latency_samples: int


def _sinc(value: float) -> float:
    return 1.0 if value == 0 else math.sin(math.pi * value) / (math.pi * value)


def _resample(channel: tuple[float, ...], source_rate: int, target_rate: int) -> tuple[float, ...]:
    if source_rate == target_rate:
        return channel
    target_frames = round(len(channel) * target_rate / source_rate)
    radius = 24
    cutoff = min(1.0, target_rate / source_rate)
    result = []
    for frame in range(target_frames):
        source_position = frame * source_rate / target_rate
        center = math.floor(source_position)
        weighted = 0.0
        total = 0.0
        for index in range(center - radius + 1, center + radius + 1):
            offset = source_position - index
            if abs(offset) >= radius:
                continue
            # Symmetric finite sinc avoids a group-delay shift; the low-pass
            # cutoff also suppresses aliases when converting downwards.
            window = 0.5 + 0.5 * math.cos(math.pi * offset / radius)
            weight = cutoff * _sinc(cutoff * offset) * window
            total += weight
            if 0 <= index < len(channel):
                weighted += channel[index] * weight
        result.append(weighted / total if total else 0.0)
    return tuple(result)


def align_stems(stems: tuple[Stem, ...], sample_rate: int = 48_000) -> tuple[AlignedStem, ...]:
    """Convert and zero-pad stems so their calibrated reference events coincide.

    This returns separate mono/stereo stems. It never sums, normalizes, trims,
    or duplicates channels; the caller decides how to route each stem.
    """

    if not stems or sample_rate <= 0:
        raise ValueError("at least one stem and a positive sample rate are required")
    converted = [
        tuple(_resample(channel, stem.sample_rate, sample_rate) for channel in stem.channels)
        for stem in stems
    ]
    placements = [
        round(stem.start_s * sample_rate)
        - round(stem.measured_latency_samples * sample_rate / stem.sample_rate)
        for stem in stems
    ]
    leading = max(0, -min(placements))
    shifted = [placement + leading for placement in placements]
    duration = max(placement + len(audio[0]) for placement, audio in zip(shifted, converted))
    return tuple(
        AlignedStem(
            channels=tuple(
                (0.0,) * placement + channel + (0.0,) * (duration - placement - len(channel))
                for channel in audio
            ),
            sample_rate=sample_rate,
            placement_frame=placement,
            common_reference_frame=round(stem.start_s * sample_rate) + leading,
            source_frames=len(stem.channels[0]),
            converted_frames=len(audio[0]),
            measured_latency_samples=stem.measured_latency_samples,
        )
        for stem, audio, placement in zip(stems, converted, shifted)
    )
