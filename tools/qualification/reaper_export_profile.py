"""Bounded offline REAPER export from a disposable project copy with an explicit profile."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import wave


BASE = Path('/private/tmp/llm-studio-reaper')
REAPER = Path('/Applications/REAPER.app/Contents/MacOS/REAPER')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--cfgfile', required=True, type=Path)
    parser.add_argument('--timeout-sec', type=float, default=30)
    parser.add_argument('--omit-cfgfile', action='store_true',
                        help='diagnostic only: reproduce the upstream controller command')
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    cfgfile = args.cfgfile.resolve(strict=True)
    if not source.is_relative_to(BASE) or source.suffix.lower() != '.rpp':
        parser.error('source must be a disposable RPP')
    if not cfgfile.is_relative_to(BASE) or cfgfile.name != 'reaper.ini':
        parser.error('cfgfile must be a disposable REAPER profile')
    if not 5 <= args.timeout_sec <= 60:
        parser.error('timeout must be 5..60 seconds')
    root = Path(tempfile.mkdtemp(prefix='gate-a4-export-', dir=BASE))
    project = root / 'session.RPP'
    shutil.copy2(source, project)
    from reaper_connector import rpp
    wav = root / 'mix.wav'
    rendercopy = root / 'session.rendercopy.rpp'
    rpp.patch_render_file(project, rendercopy, str(wav))
    command = [str(REAPER)]
    if not args.omit_cfgfile:
        command += ['-cfgfile', str(cfgfile)]
    command += ['-renderproject', str(rendercopy)]
    result = {'source': str(source), 'copy': str(rendercopy), 'output': str(wav),
              'cfgfile': str(cfgfile) if not args.omit_cfgfile else None,
              'command': command, 'timeout_sec': args.timeout_sec}
    started = time.monotonic()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    result['child_pid'] = process.pid
    try:
        stdout, stderr = process.communicate(timeout=args.timeout_sec)
        result['timed_out'] = False
    except subprocess.TimeoutExpired:
        result['timed_out'] = True
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=3)
    result.update(elapsed_sec=round(time.monotonic() - started, 3),
                  returncode=process.returncode, stdout_tail=stdout[-2000:],
                  stderr_tail=stderr[-2000:], wav_exists=wav.is_file(),
                  wav_bytes=wav.stat().st_size if wav.is_file() else 0)
    if wav.is_file():
        with wave.open(str(wav), 'rb') as audio:
            result['audio'] = {'channels': audio.getnchannels(),
                               'sample_rate': audio.getframerate(),
                               'frames': audio.getnframes(),
                               'duration_sec': audio.getnframes() / audio.getframerate()}
    result['ok'] = not result['timed_out'] and result['returncode'] == 0 and result['wav_bytes'] > 0
    (root / 'export-evidence.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2), flush=True)
    if not result['ok']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
