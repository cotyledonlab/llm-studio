"""Prepare/run native #10 qualification against a COPY of a disposable session.

The active source must match --source exactly and be stopped. The harness leaves
its saved copy available and restores the original tab. Explicit --cfgfile avoids
accidentally forwarding to a different REAPER profile. No DAW GUI automation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import tempfile
import time
import wave


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--cfgfile', required=True, type=Path)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    source, profile = args.source.resolve(strict=True), args.cfgfile.resolve(strict=True)
    base = Path('/private/tmp/llm-studio-reaper')
    if not source.is_relative_to(base) or source.suffix.lower() != '.rpp':
        parser.error('source must be a saved disposable RPP under /private/tmp/llm-studio-reaper')
    root = Path(tempfile.mkdtemp(prefix='automation-', dir=base))
    media = root / 'media'
    media.mkdir()
    tone = root / 'tone.wav'
    with wave.open(str(tone), 'wb') as out:
        out.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        out.writeframes(b''.join(struct.pack('<h', round(3000 * math.sin(2 * math.pi * 440 * i / 48000))) for i in range(240000)))
    stem = media / (hashlib.sha256(tone.read_bytes()).hexdigest() + '.wav')
    tone.rename(stem)
    repo = Path(__file__).resolve().parents[2]
    config = dict(root=str(root), source=str(source), profile=str(profile.parent), stem=str(stem),
                  handler=str(repo / 'adapters/reaper/studio_handler.lua'))
    wrapper = root / 'run.lua'
    wrapper.write_text('STUDIO_AUTOMATION = {\n' + ''.join(
        f'  {key} = {json.dumps(value)},\n' for key, value in config.items()) + '}\n' +
        f'dofile({json.dumps(str(Path(__file__).with_suffix(".lua")))})\n')
    print(root, flush=True)
    if args.run:
        subprocess.run(['/Applications/REAPER.app/Contents/MacOS/REAPER', '-cfgfile', str(profile),
                        '-nonewinst', '-noactivate', str(wrapper)], check=True, timeout=20)
        report = root / 'native-evidence.txt'
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            evidence = report.read_text() if report.exists() else ''
            if 'source_revision_unchanged=' in evidence:
                if not all(marker in evidence for marker in (
                        'native_qualification=pass', 'source_tab_restored=true',
                        'source_revision_unchanged=true')):
                    raise RuntimeError(f'native qualification failed; inspect {report}')
                print(f'Native qualification passed: {report}')
                break
            time.sleep(.05)
        else:
            raise TimeoutError(f'native completion unobserved; inspect {report} before retrying')


if __name__ == '__main__':
    main()
