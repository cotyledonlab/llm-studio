import math
from pathlib import Path
import struct
import wave

from tools.qualification.reaper_automation_audio_compare import compare


def _write(path: Path, *, changed: bool) -> None:
    rate = 8000
    with wave.open(str(path), "wb") as stream:
        stream.setparams((2, 2, rate, 0, "NONE", "not compressed"))
        frames = []
        for index in range(rate * 4):
            time_sec = index / rate
            gain = 0.7 if changed and 1.1 <= time_sec <= 2.9 else 0.25
            sample = round(12000 * gain * math.sin(2 * math.pi * 220 * time_sec))
            frames.append(struct.pack("<hh", sample, sample))
        stream.writeframes(b"".join(frames))


def test_automation_audio_comparison_proves_scoped_change(tmp_path):
    baseline = tmp_path / "baseline.wav"
    processed = tmp_path / "processed.wav"
    _write(baseline, changed=False)
    _write(processed, changed=True)

    result = compare(baseline, processed, start=1, end=3)

    assert result["ok"] is True
    assert result["exterior_delta_rms"] == 0
    assert result["interior_delta_rms"] > 0
