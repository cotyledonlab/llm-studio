"""Measure the controlled mono fixture rendered at unity/centre and half/right."""
import argparse
import json
import math
from pathlib import Path
import wave


def measure(path):
    with wave.open(str(path), 'rb') as stream:
        channels, width, rate, frames = stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getnframes()
        if channels != 2 or width not in (2, 3, 4) or frames == 0:
            raise ValueError('requires nonempty stereo PCM WAV')
        raw = stream.readframes(frames)
    samples = [int.from_bytes(raw[i:i + width], 'little', signed=True) / 2 ** (width * 8 - 1) for i in range(0, len(raw), width)]
    rms = [math.sqrt(sum(value * value for value in samples[channel::2]) / frames) for channel in range(2)]
    return {'rate': rate, 'frames': frames, 'rms': rms, 'peak': max(map(abs, samples))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    baseline = measure(args.directory / 'baseline.wav')
    processed = measure(args.directory / 'processed.wav')
    ratio = processed['rms'][1] / baseline['rms'][1] if baseline['rms'][1] else None
    ok = (baseline['rate'] == processed['rate'] and baseline['frames'] == processed['frames']
          and .001 < baseline['peak'] < .99 and .001 < processed['peak'] < .99
          and math.isclose(baseline['rms'][0], baseline['rms'][1], rel_tol=1e-4)
          and processed['rms'][0] < 1e-6 and ratio is not None and math.isclose(ratio, .5, rel_tol=.01))
    print(json.dumps({'ok': ok, 'baseline': baseline, 'processed': processed, 'right_gain_ratio': ratio}, indent=2))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
