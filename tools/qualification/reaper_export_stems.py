"""Render and measure aligned REAPER part exports from an immutable A4 copy."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
import wave


BASE = Path('/private/tmp/llm-studio-reaper')
REAPER = Path('/Applications/REAPER.app/Contents/MacOS/REAPER')
TRACK = re.compile(r'(?ms)^  <TRACK [^\n]*\n.*?^  >$')
ITEM = re.compile(r'(?ms)^    <ITEM\n(.*?)^    >$')


def expected_project_duration(source: Path) -> float:
    """Return the A4 fixture's full-project, zero-extra-tail render bound."""
    text = source.read_text()
    render_range = re.search(r'(?m)^  RENDER_RANGE (\d+)(?:\s|$)', text)
    if not render_range or render_range.group(1) != '1':
        raise ValueError('A4 render must use the full-project range')
    items = ITEM.findall(text)
    if not items:
        raise ValueError('A4 project has no media items to establish its render bound')
    ends = []
    for block in items:
        position = re.search(r'(?m)^      POSITION ([^\s]+)$', block)
        length = re.search(r'(?m)^      LENGTH ([^\s]+)$', block)
        if not position or not length:
            raise ValueError('A4 media item is missing position or length')
        start, duration = float(position.group(1)), float(length.group(1))
        if not math.isfinite(start) or not math.isfinite(duration) or duration <= 0:
            raise ValueError('A4 media item has invalid position or length')
        ends.append(start + duration)
    return max(ends)


def read_pcm(path: Path) -> tuple[int, int, list[tuple[int, int]]]:
    with wave.open(str(path), 'rb') as audio:
        channels, width, rate, frames = (audio.getnchannels(), audio.getsampwidth(),
                                         audio.getframerate(), audio.getnframes())
        if channels != 2 or width not in (2, 3, 4) or frames <= 0:
            raise ValueError('requires nonempty stereo PCM WAV')
        raw = audio.readframes(frames)
    values = [int.from_bytes(raw[i:i + width], 'little', signed=True)
              for i in range(0, len(raw), width)]
    return rate, width, list(zip(values[::2], values[1::2]))


def rms(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values) / len(values)) if values else 0


def window_rms(frames: list[tuple[int, int]], rate: int, start: float, end: float,
               channel: int | None = None) -> float:
    section = frames[round(start * rate):round(end * rate)]
    values = [frame[channel] for frame in section] if channel is not None else [
        value for frame in section for value in frame]
    return rms(values)


def tone_magnitude(frames: list[tuple[int, int]], rate: int, frequency: int) -> float:
    segment = frames[round(rate * 2.4):round(rate * 2.6)]
    sine = cosine = 0.0
    for index, frame in enumerate(segment):
        angle = 2 * math.pi * frequency * index / rate
        sample = (frame[0] + frame[1]) / 2
        sine += sample * math.sin(angle)
        cosine += sample * math.cos(angle)
    return 2 * math.hypot(sine, cosine) / len(segment)


def saved_bass_gain(source: Path) -> float:
    """Read the Bass track's saved VOLPAN gain from an RPP without REAPER."""
    text = source.read_text()
    bass_blocks = []
    for match in TRACK.finditer(text):
        block = match.group()
        name = re.search(r'(?m)^    NAME ([^\n]+)$', block)
        if name and name.group(1) == 'Bass':
            bass_blocks.append(block)
    if len(bass_blocks) != 1:
        raise ValueError(f'expected exactly one saved Bass track, found {len(bass_blocks)}')
    volpan = re.search(r'(?m)^    VOLPAN ([^\s]+)(?:\s|$)', bass_blocks[0])
    if not volpan:
        raise ValueError('saved Bass track has no VOLPAN gain')
    gain = float(volpan.group(1))
    if not math.isfinite(gain):
        raise ValueError('saved Bass track has an invalid VOLPAN gain')
    return gain


def validate_bass_export(source: Path, frames: list[tuple[int, int]], rate: int,
                         expect_silent: bool) -> dict:
    """Validate either the ordinary pan signature or a saved zero-gain Bass."""
    left = window_rms(frames, rate, 2.4, 2.6, 0)
    right = window_rms(frames, rate, 2.4, 2.6, 1)
    if not expect_silent:
        return {'ok': left > right * 1.05, 'mode': 'pan', 'left_rms': left,
                'right_rms': right}
    gain = saved_bass_gain(source)
    peak = max((abs(sample) for frame in frames for sample in frame), default=0)
    return {'ok': gain == 0 and peak <= 1, 'mode': 'silent',
            'saved_gain': gain, 'max_abs_sample_lsb': peak,
            'allowed_max_abs_sample_lsb': 1, 'left_rms': left,
            'right_rms': right}


def muted_project(source: Path, output: Path, part: str, wav: Path) -> None:
    from reaper_connector import rpp
    rpp.patch_render_file(source, output, str(wav))
    text = output.read_text()
    seen = []
    def replace(match: re.Match[str]) -> str:
        block = match.group()
        name = re.search(r'(?m)^    NAME (Keys|Bass|Drums)$', block)
        if not name:
            raise ValueError('unexpected track in A4 fixture')
        seen.append(name.group(1))
        muted = '0' if name.group(1) == part else '1'
        block, count = re.subn(r'(?m)^    MUTESOLO [^\n]*$',
                               '    MUTESOLO ' + muted + ' 0 0', block, count=1)
        if count != 1:
            raise ValueError('missing track mute state')
        return block
    text = TRACK.sub(replace, text)
    if seen != ['Keys', 'Bass', 'Drums']:
        raise ValueError(f'unexpected A4 track set: {seen}')
    output.write_text(text)


def render(project: Path, cfgfile: Path, wav: Path) -> dict:
    command = [str(REAPER), '-cfgfile', str(cfgfile), '-renderproject', str(project)]
    started = time.monotonic()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=30)
    except subprocess.TimeoutExpired as error:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=3)
        raise TimeoutError(f'REAPER stem render timed out: {project}') from error
    result = {'project': str(project), 'wav': str(wav), 'pid': process.pid,
              'elapsed_sec': round(time.monotonic() - started, 3),
              'returncode': process.returncode, 'stdout_tail': stdout[-1000:],
              'stderr_tail': stderr[-1000:], 'wav_bytes': wav.stat().st_size if wav.is_file() else 0}
    if process.returncode != 0 or not wav.is_file() or wav.stat().st_size == 0:
        raise RuntimeError(f'stem export failed: {result}')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--cfgfile', required=True, type=Path)
    parser.add_argument('--mix', required=True, type=Path)
    parser.add_argument('--expect-silent-bass', action='store_true',
                        help='require saved Bass gain zero and a silent Bass stem')
    args = parser.parse_args()
    source, cfgfile, mix = (args.source.resolve(strict=True),
                            args.cfgfile.resolve(strict=True), args.mix.resolve(strict=True))
    if (not source.is_relative_to(BASE) or not cfgfile.is_relative_to(BASE)
            or not mix.is_relative_to(BASE)):
        parser.error('all inputs must be under the disposable REAPER root')
    root = Path(tempfile.mkdtemp(prefix='gate-a4-stems-', dir=BASE))
    rendered = {}
    for part in ('Keys', 'Bass', 'Drums'):
        wav = root / f'{part.lower()}.wav'
        project = root / f'{part.lower()}.RPP'
        muted_project(source, project, part, wav)
        rendered[part] = render(project, cfgfile, wav)
    mix_rate, mix_width, mix_frames = read_pcm(mix)
    audio = {part: read_pcm(root / f'{part.lower()}.wav') for part in rendered}
    expected_duration = expected_project_duration(source)
    expected_frames = round(expected_duration * mix_rate)
    expected_bounds = (len(mix_frames) == expected_frames and all(
        len(frames) == expected_frames for _, _, frames in audio.values()))
    aligned = all(rate == mix_rate and width == mix_width and len(frames) == len(mix_frames)
                  for rate, width, frames in audio.values())
    if not aligned or not expected_bounds:
        raise RuntimeError(
            f'exports do not match project bounds: expected {expected_frames} frames '
            f'({expected_duration:g}s), mix has {len(mix_frames)}, '
            f'stems have {[len(frames) for _, _, frames in audio.values()]}')
    sums = [tuple(sum(audio[part][2][i][channel] for part in rendered)
                  for channel in (0, 1)) for i in range(len(mix_frames))]
    errors = [mix_frames[i][channel] - sums[i][channel]
              for i in range(len(mix_frames)) for channel in (0, 1)]
    reference = rms([value for frame in mix_frames for value in frame])
    error_ratio = rms(errors) / reference if reference else math.inf
    keys = audio['Keys'][2]
    bass = audio['Bass'][2]
    drums = audio['Drums'][2]
    keys_early = window_rms(keys, mix_rate, .4, .6)
    keys_mid = window_rms(keys, mix_rate, 2.4, 2.6)
    keys_late = window_rms(keys, mix_rate, 4.4, 4.6)
    bass_left = window_rms(bass, mix_rate, 2.4, 2.6, 0)
    bass_right = window_rms(bass, mix_rate, 2.4, 2.6, 1)
    bass_check = validate_bass_export(source, bass, mix_rate, args.expect_silent_bass)
    drums_440 = tone_magnitude(drums, mix_rate, 440)
    drums_330 = tone_magnitude(drums, mix_rate, 330)
    result = {'ok': aligned and expected_bounds and error_ratio < 1e-5 and keys_mid < keys_early * .05
              and keys_late > keys_early * .2 and bass_check['ok']
              and drums_440 > drums_330 * 100,
              'source': str(source), 'mix': str(mix), 'root': str(root),
              'sample_rate': mix_rate, 'sample_width_bytes': mix_width,
              'frames': len(mix_frames), 'duration_sec': len(mix_frames) / mix_rate,
              'expected_project_duration_sec': expected_duration,
              'expected_extra_tail_sec': 0.0,
              'tail_bound': 'A4 source items end at the full-project render bound; no extra tail is configured',
              'expected_frames': expected_frames, 'expected_bounds': expected_bounds,
              'aligned': aligned, 'summed_stem_error_rms_ratio': error_ratio,
              'max_summed_stem_error_lsb': max(abs(value) for value in errors),
              'keys_rms': {'early': keys_early, 'mid': keys_mid, 'late': keys_late},
              'bass_rms': {'left': bass_left, 'right': bass_right},
              'bass_check': bass_check,
              'drums_tone_magnitude': {'accepted_440hz': drums_440, 'replaced_330hz': drums_330},
              'renders': rendered}
    (root / 'audio-evidence.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2), flush=True)
    if not result['ok']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
