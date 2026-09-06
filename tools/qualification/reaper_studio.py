"""Prepare or run native disposable REAPER handler qualification.

No GUI automation. A stopped producer transport is required. The Lua script
opens a disposable tab and restores the original project selection. It leaves
the disposable tab and all evidence in place for inspection.
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
import wave


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true', help='Execute the prepared script through native REAPER CLI')
    args = parser.parse_args()
    base = Path('/private/tmp/llm-studio-reaper')
    base.mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='qualification-', dir=base))
    media = root / 'media'
    media.mkdir()
    source = root / 'fixture.wav'
    with wave.open(str(source), 'wb') as out:
        out.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        out.writeframes(b''.join(struct.pack('<h', round(3000 * math.sin(2 * math.pi * 440 * i / 48000))) for i in range(48000)))
    stem = media / (hashlib.sha256(source.read_bytes()).hexdigest() + '.wav')
    stem.write_bytes(source.read_bytes())
    repo = Path(__file__).resolve().parents[2]
    # JSON string quoting is Lua-compatible for these controlled ASCII paths.
    config = {'root': str(root), 'stem': str(stem), 'handler': str(repo / 'adapters/reaper/studio_handler.lua')}
    wrapper = root / 'run.lua'
    wrapper.write_text('STUDIO_QUAL = {\n' + ''.join(f'  {key} = {json.dumps(value)},\n' for key, value in config.items()) + '}\n' + f'dofile({json.dumps(str(Path(__file__).with_suffix(".lua")))})\n')
    print(root, flush=True)
    if args.run:
        subprocess.run(['/Applications/REAPER.app/Contents/MacOS/REAPER', '-nonewinst', '-noactivate', str(wrapper)], check=True, timeout=20)


if __name__ == '__main__':
    main()
