"""Qualify issue #11 take replacement on a copy of the active disposable session."""
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


BASE = Path('/private/tmp/llm-studio-reaper')
REAPER = Path('/Applications/REAPER.app/Contents/MacOS/REAPER')


def wait_for_active_copy(snapshot, expected: Path, *, timeout: float = 20,
                         interval: float = 0.05) -> None:
    """Wait for an independent REAPER snapshot before dispatching stage two."""
    deadline = time.monotonic() + timeout
    last_path = None
    last_error = None
    while True:
        try:
            session = snapshot()
            last_path = session.get('path') if isinstance(session, dict) else None
            last_error = None
            if last_path == str(expected):
                return
        except Exception as error:
            last_error = str(error)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f'active-copy observation timed out: expected={expected}, '
                f'observed={last_path}, last_error={last_error}')
        time.sleep(min(interval, remaining))


def tone(path: Path, frequency: int) -> None:
    with wave.open(str(path), 'wb') as output:
        output.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        output.writeframes(b''.join(struct.pack('<h', round(2300 * math.sin(
            2 * math.pi * frequency * i / 48000))) for i in range(240000)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--cfgfile', required=True, type=Path)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    cfgfile = args.cfgfile.resolve(strict=True)
    if not source.is_relative_to(BASE) or source.suffix.lower() != '.rpp':
        parser.error('source must be a disposable RPP')
    if not cfgfile.is_relative_to(BASE) or cfgfile.name != 'reaper.ini':
        parser.error('cfgfile must be a disposable REAPER profile')
    root = Path(tempfile.mkdtemp(prefix='gate-a4-', dir=BASE))
    media = root / 'media'
    media.mkdir()
    stems = {}
    for name, frequency in [('keys', 220), ('bass', 110),
                            ('drums_a', 330), ('drums_b', 440)]:
        draft = root / f'{name}.wav'
        tone(draft, frequency)
        destination = media / f'{hashlib.sha256(draft.read_bytes()).hexdigest()}.wav'
        draft.rename(destination)
        stems[name] = str(destination)
    repo = Path(__file__).resolve().parents[2]
    config = {'root': str(root), 'source': str(source), 'profile': str(cfgfile.parent),
              'handler': str(repo / 'adapters/reaper/studio_handler.lua'), **stems}
    wrapper = root / 'run.lua'
    wrapper.write_text('STUDIO_TAKE_REPLACEMENT = {\n' + ''.join(
        f'  {key} = {json.dumps(value)},\n' for key, value in config.items())
        + '}\n' + f'dofile({json.dumps(str(Path(__file__).with_suffix(".lua")))})\n')
    reopen = root / 'reopen.lua'
    reopen.write_text('STUDIO_TAKE_REPLACEMENT = {\n' + ''.join(
        f'  {key} = {json.dumps(value)},\n' for key, value in config.items())
        + '}\n' + f'dofile({json.dumps(str(Path(__file__).with_name("reaper_take_replacement_reopen.lua")))})\n')
    print(root, flush=True)
    if not args.run:
        return
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    subprocess.run([str(REAPER), '-cfgfile', str(cfgfile), '-nonewinst', '-noactivate',
                    str(wrapper)], check=True, timeout=20)
    report = root / 'native-evidence.txt'
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        evidence = report.read_text() if report.exists() else ''
        if 'source_tab_restored=' in evidence and 'pre_reopen_complete=pass' not in evidence:
            raise RuntimeError(f'first native stage failed; inspect {report}')
        if 'pre_reopen_complete=pass' in evidence:
            break
        time.sleep(.05)
    else:
        raise TimeoutError(f'first native stage unobserved; inspect {report} before retrying')

    # The stage-one marker is written immediately before Main_openProject,
    # which ends that ReaScript. Confirm the live tab switch independently
    # through the installed bridge before asking REAPER to run stage two.
    from reaper_connector.bridge import send

    def snapshot() -> dict:
        reply = send('studio.session_snapshot', {}, timeout=2,
                     resource_path=cfgfile.parent)
        if reply.get('ok') is not True or not isinstance(reply.get('result'), dict):
            raise RuntimeError(f'incomplete session snapshot: {reply!r}')
        session = reply['result'].get('session')
        if not isinstance(session, dict):
            raise RuntimeError(f'session identity missing from snapshot: {reply!r}')
        return session

    wait_for_active_copy(snapshot, root / 'session.RPP')
    subprocess.run([str(REAPER), '-cfgfile', str(cfgfile), '-nonewinst', '-noactivate',
                    str(reopen)], check=True, timeout=20)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        evidence = report.read_text()
        if 'source_tab_restored=' in evidence:
            if not all(marker in evidence for marker in (
                    'native_qualification=pass', 'source_tab_restored=true',
                    'source_revision_unchanged=true', 'source_dirty_unchanged=true')):
                raise RuntimeError(f'native qualification failed; inspect {report}')
            if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
                raise RuntimeError('source RPP bytes changed; inspect before further work')
            print(f'Native qualification passed: {report}')
            return
        time.sleep(.05)
    raise TimeoutError(f'reopen readback unobserved; inspect {report} before retrying')


if __name__ == '__main__':
    main()
