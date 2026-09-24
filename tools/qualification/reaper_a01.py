"""Prepare and run a focus-guarded disposable Gate A qualification.

The runner never focuses an application, clicks controls, or edits a producer
project. Start it from a desktop Terminal with another application frontmost.
For the manual fader/envelope handoff, John may focus REAPER; the runner waits
for focus to return to another application before issuing further operations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import wave
from datetime import datetime, timezone
from typing import Any, Callable


BASE = Path('/private/tmp/llm-studio-reaper')
REAPER = Path('/Applications/REAPER.app/Contents/MacOS/REAPER')
REAPER_BUNDLE_ID = 'com.cockos.reaper'
NON_USER_FRONTMOST_BUNDLE_IDS = {'com.apple.loginwindow'}
PINNED_CONTROLLER = Path('/private/tmp/reaper-controller-fd56')
MANIFEST_NAME = 'a01-manifest.json'
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'src'))
FILE_LINE = re.compile(r'(?m)^(\s*FILE )"([^"]+)"$')
TRACK = re.compile(r'(?ms)^  <TRACK (\{[^}]+\})[^\r\n]*\r?\n(.*?)^  >$')
ITEM = re.compile(r'(?ms)^    <ITEM\s*\r?\n(.*?)^    >$')


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if value is None or type(value) in (str, int, float, bool):
        return value
    if hasattr(value, '__dataclass_fields__'):
        return plain({name: getattr(value, name) for name in value.__dataclass_fields__})
    return repr(value)


def _safe_path(path: Path, *, parent: Path, suffix: str | None = None) -> Path:
    raw = Path(os.path.abspath(path))
    if raw != path.absolute() or raw.is_symlink() or raw.resolve(strict=True) != raw:
        raise ValueError(f'path must be canonical and contain no symlinks: {path}')
    if not raw.is_relative_to(parent.resolve()):
        raise ValueError(f'path must be under {parent}')
    if suffix is not None and raw.suffix.lower() != suffix:
        raise ValueError(f'path must use {suffix}: {path}')
    return raw


def _project_tracks(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding='utf-8')
    tracks = []
    for match in TRACK.finditer(text):
        guid, block = match.groups()
        name = re.search(r'(?m)^    NAME (.+)$', block)
        volume = re.search(r'(?m)^    VOLPAN ([^\s]+) ([^\s]+)', block)
        items = ITEM.findall(block)
        if not name or not volume or len(items) != 1:
            raise ValueError('fixture must have named tracks with one audio item each')
        item_guid = re.search(r'(?m)^      IGUID (\{[^}]+\})$', items[0])
        position = re.search(r'(?m)^      POSITION ([^\s]+)$', items[0])
        length = re.search(r'(?m)^      LENGTH ([^\s]+)$', items[0])
        if not item_guid or not position or not length:
            raise ValueError(f'{name.group(1)} item is missing identity or geometry')
        fx = re.findall(r'(?m)^\s*<VST "([^"]+)"', block)
        tracks.append({
            'guid': guid, 'name': name.group(1), 'volume': float(volume.group(1)),
            'pan': float(volume.group(2)), 'fx': fx,
            'item_guid': item_guid.group(1), 'position_sec': float(position.group(1)),
            'length_sec': float(length.group(1)),
        })
    if tuple(track['name'] for track in tracks) != ('Keys', 'Bass', 'Drums'):
        raise ValueError('source fixture must contain Keys, Bass, and Drums in that order')
    return tracks


def _write_tone(path: Path, *, duration: float, frequency: int, rate: int = 48000) -> dict[str, Any]:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f'refusing to overwrite audio fixture: {path}')
    frames = round(duration * rate)
    if frames <= 0 or not math.isclose(frames / rate, duration, rel_tol=0, abs_tol=1e-9):
        raise ValueError('tone duration must resolve to a positive integral frame count')
    import struct
    import math as math_module
    values = (round(3500 * math_module.sin(2 * math.pi * frequency * i / rate))
              for i in range(frames))
    with path.open('xb') as raw:
        with wave.open(raw, 'wb') as out:
            out.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
            out.writeframes(b''.join(struct.pack('<h', sample) for sample in values))
    return {'path': str(path), 'sha256': sha256(path), 'duration_sec': frames / rate,
            'frequency_hz': frequency, 'sample_rate': rate, 'channels': 1}


def prepare_fixture(source: Path, root: Path) -> dict[str, Any]:
    source = _safe_path(source, parent=BASE, suffix='.rpp')
    root = Path(os.path.abspath(root))
    if not root.is_relative_to(BASE) or root.exists() or root.is_symlink():
        raise ValueError('run root must be a new path directly under the disposable REAPER root')
    if root.parent.resolve() != BASE.resolve():
        raise ValueError('run root must be a direct child of the disposable REAPER root')
    layout = _project_tracks(source)
    text = source.read_text(encoding='utf-8')
    references = [match.group(2) for match in FILE_LINE.finditer(text)]
    if not references:
        raise ValueError('source RPP contains no audio FILE references')
    root.mkdir(mode=0o700)
    media = root / 'media'
    media.mkdir(mode=0o700)
    copied = []
    for raw_ref in references:
        ref = Path(raw_ref)
        original = ref if ref.is_absolute() else source.parent / ref
        original = _safe_path(original, parent=BASE)
        if not original.is_file():
            raise ValueError(f'fixture asset is not a regular disposable audio file: {original}')
        digest = sha256(original)
        destination = media / f'{digest}{original.suffix.lower()}'
        if destination.exists():
            if sha256(destination) != digest:
                raise ValueError(f'asset hash collision at {destination}')
        else:
            shutil.copyfile(original, destination)
        text = text.replace(f'FILE "{raw_ref}"', f'FILE "{destination}"')
        copied.append({'source': str(original), 'source_sha256': digest,
                       'copy': str(destination), 'sha256': sha256(destination)})
    project = root / 'session.RPP'
    if project.exists():
        raise FileExistsError(project)
    with project.open('x', encoding='utf-8') as stream:
        stream.write(text)
    last_end = max(track['position_sec'] + track['length_sec'] for track in layout)
    import_tone = _write_tone(root / 'import-660hz.wav', duration=1.0, frequency=660)
    replacement = _write_tone(root / 'replacement-440hz.wav', duration=layout[-1]['length_sec'],
                              frequency=440)
    manifest = {
        'schema': 'llm-studio.reaper-gate-a01.v1', 'state': 'prepared',
        'created_at_utc': utc_now(), 'root': str(root), 'source_project': str(source),
        'source_project_sha256': sha256(source), 'project': str(project),
        'project_sha256': sha256(project), 'tracks': layout,
        'source_assets': copied, 'import_tone': import_tone,
        'replacement_tone': replacement, 'import_position_sec': last_end,
        'expected_track_names': ['Keys', 'Bass', 'Drums'],
        'notes': ['Project and media are unique disposable copies.',
                  'No REAPER process was started and no source project was changed.'],
    }
    with (root / MANIFEST_NAME).open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write('\n')
    return manifest


def prepare_profiles(root: Path, controller: Path, license_source: Path) -> dict[str, Any]:
    from llm_studio import bootstrap
    from tools.qualification.install_profile_license import install_license

    root = root.resolve(strict=True)
    manifest_path = root / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('state') != 'prepared' or 'profile' in manifest:
        raise ValueError('profiles can only be prepared once for a fresh fixture')
    controller = _safe_path(controller, parent=Path('/private/tmp'))
    if controller != PINNED_CONTROLLER:
        raise ValueError(f'controller must be the pinned disposable checkout at {PINNED_CONTROLLER}')
    license_source = Path(license_source).resolve(strict=True)
    profile_parent = root / 'profile'
    resource = profile_parent / 'resource'
    render_parent = root / 'render-profile'
    render_resource = render_parent / 'resource'
    journal = root / 'a01-prepare-focus.jsonl'
    if any(path.exists() or path.is_symlink() for path in (profile_parent, render_parent, journal)):
        raise FileExistsError('profile preparation paths already exist')
    probe = FocusProbe(root)
    probe.build()
    gate = FocusGate(probe, journal)

    def create_main_profile() -> dict[str, Any]:
        profile_parent.mkdir(mode=0o700)
        resource.mkdir(mode=0o700)
        plan = bootstrap.plan_bootstrap(resource, controller, PROJECT_ROOT)
        result = bootstrap.apply(plan, running=lambda: False, isolated_empty_profile=True)
        verified = bootstrap.verify(result)
        if not verified['ok']:
            raise RuntimeError('isolated bootstrap hashes or directories failed readback')
        return {'receipt': str(result.backup_dir) if result.backup_dir else None,
                'changed': list(result.changed), 'unchanged': list(result.unchanged),
                'verify': verified}

    main_result = gate.step('isolated profile bootstrap', create_main_profile)
    license_target = gate.step('copy protected license to isolated profile',
                               lambda: install_license(license_source, resource))

    def create_render_profile() -> dict[str, Any]:
        render_parent.mkdir(mode=0o700)
        render_resource.mkdir(mode=0o700)
        ini = render_resource / 'reaper.ini'
        with ini.open('x', encoding='utf-8') as stream:
            stream.write('[REAPER]\n')
        render_license = install_license(license_source, render_resource)
        return {'resource': str(render_resource), 'ini_sha256': sha256(ini),
                'license_installed': render_license.is_file()}

    render_result = gate.step('separate render profile setup', create_render_profile)
    manifest['profile'] = {
        'resource': str(resource), 'render_resource': str(render_resource),
        'bootstrap': main_result, 'license_installed': license_target.is_file(),
        'render_profile': render_result,
    }
    manifest['profile_prepared_at_utc'] = utc_now()
    _new_json(root / 'a01-manifest-profile.json', manifest)
    return manifest['profile']


class FocusProbe:
    def __init__(self, root: Path):
        self.root = root
        self.executable = root / 'a01-focus-probe'

    def build(self) -> None:
        cache = self.root / '.swift-module-cache'
        command = ['swiftc', '-module-cache-path', str(cache), '-o', str(self.executable),
                   str(Path(__file__).with_name('reaper_a01_focus.swift'))]
        result = subprocess.run(command, capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise RuntimeError(f'focus observer build failed: {result.stderr[-2000:]}')

    def read(self) -> dict[str, Any]:
        result = subprocess.run([str(self.executable)], capture_output=True, text=True, timeout=5)
        if result.returncode:
            raise RuntimeError(f'frontmost app is not observable: {result.stderr.strip()}')
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f'focus observer returned invalid JSON: {result.stdout!r}') from exc
        if (not isinstance(data.get('name'), str) or not data['name']
                or not isinstance(data.get('bundle_id'), str) or not data['bundle_id']
                or type(data.get('process_id')) is not int
                or not isinstance(data.get('observed_at_utc'), str)):
            raise RuntimeError(f'focus observer returned incomplete app metadata: {data!r}')
        return data


class FocusGate:
    """Require a non-REAPER frontmost app before, during, and after each step."""

    def __init__(self, probe: FocusProbe, journal: Path, *, interval: float = 0.15):
        self.probe = probe
        self.journal = journal
        self.interval = interval
        self._lock = threading.Lock()

    def _append(self, event: dict[str, Any]) -> None:
        with self._lock, self.journal.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(plain(event), sort_keys=True) + '\n')
            stream.flush()
            os.fsync(stream.fileno())

    def manual_handoff(self, instruction: str) -> dict[str, Any]:
        before = self.probe.read()
        self._append({'event': 'manual-handoff-begins', 'at_utc': utc_now(),
                      'instruction': instruction, 'focus_before': before})
        input(instruction + '\nAfter editing, switch to another app and press Return here. ')
        after = self.probe.read()
        record = {'event': 'manual-handoff-ends', 'at_utc': utc_now(),
                  'focus_after': after, 'reaper_frontmost_after':
                      after['bundle_id'] == REAPER_BUNDLE_ID}
        self._append(record)
        if after['bundle_id'] == REAPER_BUNDLE_ID or after['bundle_id'] in NON_USER_FRONTMOST_BUNDLE_IDS:
            raise RuntimeError('manual handoff not accepted: select a user app other than REAPER before continuing')
        return record

    def step(self, name: str, operation: Callable[[], Any]) -> Any:
        before = self.probe.read()
        if before['bundle_id'] == REAPER_BUNDLE_ID or before['bundle_id'] in NON_USER_FRONTMOST_BUNDLE_IDS:
            self._append({'event': 'refused', 'step': name, 'at_utc': utc_now(),
                          'reason': 'no eligible user application is frontmost', 'focus': before})
            raise RuntimeError(f'{name}: refused because no eligible user application is frontmost')
        samples: list[dict[str, Any]] = []
        stop = threading.Event()
        failures: list[str] = []

        def observe() -> None:
            while not stop.wait(self.interval):
                try:
                    samples.append(self.probe.read())
                except Exception as error:
                    failures.append(f'{type(error).__name__}: {error}')
                    return

        started = utc_now()
        self._append({'event': 'started', 'step': name, 'at_utc': started,
                      'focus': before})
        watcher = threading.Thread(target=observe, name='a01-focus-watch', daemon=True)
        watcher.start()
        value: Any = None
        operation_error: BaseException | None = None
        try:
            value = operation()
        except BaseException as error:
            operation_error = error
        finally:
            stop.set()
            watcher.join(timeout=2)
        try:
            after = self.probe.read()
        except Exception as error:
            after = None
            failures.append(f'{type(error).__name__}: {error}')
        all_focus = [before, *samples, *([after] if after else [])]
        violation = next((item for item in all_focus if item['bundle_id'] == REAPER_BUNDLE_ID
                          or item['bundle_id'] in NON_USER_FRONTMOST_BUNDLE_IDS), None)
        record = {
            'event': 'finished', 'step': name, 'started_at_utc': started,
            'finished_at_utc': utc_now(), 'focus_before': before,
            'focus_samples': samples, 'focus_after': after,
            'focus_ok': bool(after and not violation and not failures),
            'focus_violation': violation, 'focus_errors': failures,
            'operation_error': (f'{type(operation_error).__name__}: {operation_error}'
                                if operation_error else None),
            'operation_result': plain(value),
        }
        self._append(record)
        if operation_error:
            raise operation_error
        if not record['focus_ok']:
            raise RuntimeError(f'{name}: focus evidence failed after the operation; inspect the journal')
        return value


def _new_json(path: Path, value: Any) -> None:
    if os.path.lexists(path):
        raise FileExistsError(f'refusing to overwrite evidence: {path}')
    with path.open('x', encoding='utf-8') as stream:
        json.dump(plain(value), stream, indent=2, sort_keys=True)
        stream.write('\n')


def _profile_process(resource: Path) -> dict[str, Any]:
    pgrep = subprocess.run(['pgrep', '-x', 'REAPER'], capture_output=True, text=True, timeout=5)
    ps = subprocess.run(['ps', '-ww', '-axo', 'pid=,command='], capture_output=True,
                        text=True, timeout=5)
    if pgrep.returncode not in (0, 1) or ps.returncode:
        raise RuntimeError('cannot identify REAPER process(es)')
    pids = {int(item) for item in pgrep.stdout.splitlines() if item.strip()}
    expected_cfg = str((resource / 'reaper.ini').resolve(strict=True))
    hits = []
    for line in ps.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2:
            continue
        pid, command = int(fields[0]), fields[1]
        if pid not in pids or Path(command.split(None, 1)[0]).name != 'REAPER':
            continue
        argv = __import__('shlex').split(command)
        cfg_values = [argv[index + 1] for index, arg in enumerate(argv[:-1]) if arg == '-cfgfile']
        cfg_values.extend(arg.partition('=')[2] for arg in argv if arg.startswith('-cfgfile='))
        if len(cfg_values) == 1 and Path(cfg_values[0]).resolve(strict=False) == Path(expected_cfg):
            hits.append({'pid': pid, 'argv': argv})
    if len(hits) != 1:
        raise RuntimeError(f'expected exactly one REAPER using this disposable profile, found {len(hits)}')
    return hits[0]


def _copy_paths_are_private(manifest: dict[str, Any]) -> None:
    root = Path(manifest['root']).resolve(strict=True)
    project = Path(manifest['project']).resolve(strict=True)
    if not project.is_relative_to(root):
        raise ValueError('prepared project escaped its disposable run root')
    for asset in manifest['source_assets']:
        source = Path(asset['source']).resolve(strict=True)
        if sha256(source) != asset['source_sha256']:
            raise ValueError('source media changed after fixture preparation')
        copy = Path(asset['copy']).resolve(strict=True)
        if not copy.is_relative_to(root) or sha256(copy) != asset['sha256']:
            raise ValueError('prepared fixture asset path or hash changed')
    if sha256(project) != manifest['project_sha256']:
        raise ValueError('prepared RPP hash changed before qualification')


def _session_identity(session: Any) -> dict[str, Any]:
    return {'id': session.id, 'token': session.token, 'path': str(session.path),
            'state_change_count': session.state_change_count,
            'tracks': [plain(track) for track in session.tracks]}


def run_qualification(args: argparse.Namespace) -> dict[str, Any]:
    from llm_studio import bootstrap
    from llm_studio.reaper import ProposalConflict, ReaperStudioAdapter

    raw_root = Path(os.path.abspath(args.root))
    root = raw_root.resolve(strict=True)
    if raw_root != root or raw_root.is_symlink() or not root.is_relative_to(BASE):
        raise ValueError('run root must be a canonical disposable directory')
    manifest_path = root / 'a01-manifest-profile.json'
    if not manifest_path.is_file():
        raise ValueError('run profile preparation is incomplete')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    _copy_paths_are_private(manifest)
    resource = _safe_path(args.resource, parent=BASE)
    render_resource = _safe_path(Path(manifest['profile']['render_resource']), parent=BASE)
    if resource != Path(manifest['profile']['resource']):
        raise ValueError('resource differs from the profile prepared for this run')
    project = _safe_path(Path(manifest['project']), parent=BASE, suffix='.rpp')
    if not resource.is_dir() or not (resource / 'reaper.ini').is_file():
        raise ValueError('resource must be the isolated profile resource directory')
    if not (resource / 'Scripts/agent_bridge.lua').is_file() or not (resource / 'Scripts/llm_studio_reaper.lua').is_file():
        raise ValueError('installed bridge and studio handler are required')
    if args.controller.resolve(strict=True) != args.controller or args.controller != PINNED_CONTROLLER:
        raise ValueError(f'controller path must be the canonical pinned checkout {PINNED_CONTROLLER}')
    from llm_studio.bootstrap import validate_controller_checkout, plan_bootstrap, dry_run
    commit = validate_controller_checkout(args.controller)
    repo = Path(__file__).resolve().parents[2]
    plan = plan_bootstrap(resource, args.controller, repo)
    if any(file.before_hash != file.after_hash for file in plan.files):
        raise ValueError('isolated profile bootstrap differs from current pinned sources')
    if manifest.get('state') != 'prepared':
        raise ValueError('manifest is not in prepared state; refuse a second qualification run')
    if Path(manifest['root']).resolve(strict=True) != root:
        raise ValueError('manifest does not belong to the requested run root')
    journal = root / 'a01-focus.jsonl'
    report = root / 'a01-evidence.json'
    if os.path.lexists(journal) or os.path.lexists(report):
        raise FileExistsError('A01 evidence already exists; refusing to rerun this disposable session')
    probe = FocusProbe(root)
    probe.build()
    gate = FocusGate(probe, journal)
    evidence: dict[str, Any] = {
        'schema': 'llm-studio.reaper-gate-a01-evidence.v1', 'ok': False,
        'started_at_utc': utc_now(), 'root': str(root), 'resource': str(resource),
        'project': str(project), 'controller': str(args.controller),
        'controller_commit': commit, 'bootstrap_plan': dry_run(plan),
        'source_project_sha256': manifest['source_project_sha256'],
        'prepared_project_sha256': manifest['project_sha256'],
        'manual_handoff_required': True, 'steps': {},
    }

    def record(name: str, result: Any) -> Any:
        evidence['steps'][name] = plain(result)
        gate._append({'event': 'qualification-checkpoint', 'step': name,
                      'at_utc': utc_now(), 'result': plain(result)})
        return result

    connector_source = (args.controller / 'src' / 'reaper_connector').resolve(strict=True)
    sys.path.insert(0, str(args.controller / 'src'))
    import importlib.util
    connector_spec = importlib.util.find_spec('reaper_connector')
    if not connector_spec or not connector_spec.origin or not Path(connector_spec.origin).resolve().is_relative_to(connector_source):
        raise RuntimeError('reaper_connector did not resolve from the supplied pinned controller checkout')
    from reaper_connector import bridge

    def send(op: str, params: dict[str, Any]) -> dict[str, Any]:
        return gate.step(f'bridge.{op}', lambda: bridge.send(
            op, params, timeout=args.request_timeout, resource_path=resource))

    adapter = ReaperStudioAdapter(send)
    doctor_env = dict(os.environ)
    doctor_env['REAPER_RESOURCE_PATH'] = str(resource)
    doctor_env['PYTHONPATH'] = str(args.controller / 'src') + os.pathsep + doctor_env.get('PYTHONPATH', '')
    doctor = gate.step('controller doctor', lambda: subprocess.run(
        [sys.executable, '-m', 'reaper_connector', 'doctor'],
        cwd=args.controller, env=doctor_env, capture_output=True, text=True,
        timeout=20, check=True))
    record('doctor', {'python': sys.executable, 'controller_source': str(connector_source),
                      'returncode': doctor.returncode, 'stdout': doctor.stdout[-4000:],
                      'stderr': doctor.stderr[-4000:]})
    process = gate.step('isolated profile process identity', lambda: _profile_process(resource))
    record('process', process)
    render_profile_running = gate.step('separate render profile is not running', lambda:
        bootstrap.isolated_profile_running(render_resource))
    if render_profile_running:
        raise RuntimeError('render profile is already in use; choose a fresh disposable root')
    record('render_profile', {'resource': str(render_resource), 'running': False})
    session = adapter.observe_session()
    if session.path != project or tuple(t.name for t in session.tracks) != ('Keys', 'Bass', 'Drums'):
        raise ValueError('active REAPER project or track names differ from the prepared disposable fixture')
    layout = manifest['tracks']
    by_name = {track.name: track for track in session.tracks}
    if any(by_name[item['name']].guid != item['guid'] for item in layout):
        raise ValueError('active track GUIDs differ from the prepared project')
    record('session_before', _session_identity(session))
    bass, keys, drums = (by_name[name] for name in ('Bass', 'Keys', 'Drums'))
    bass_before = dict(adapter.read_track(session, bass.guid))
    keys_before = dict(adapter.read_volume_envelope(session, keys.guid, start_sec=0, end_sec=5))
    drum_layout = next(item for item in layout if item['name'] == 'Drums')
    drums_before = dict(adapter.read_stem(session, drums.guid, drum_layout['item_guid']))
    record('baseline', {'bass': bass_before, 'keys_envelope': keys_before, 'drums': drums_before})

    # Prove reversible gain/pan access before the producer handoff.
    test_mix = adapter.set_mixer(session, bass.guid, gain_db=0.0, pan=0.25)
    restored_mix = adapter.set_mixer(
        session, bass.guid,
        silent=bass_before['volume'] == 0,
        gain_db=(None if bass_before['volume'] == 0 else 20 * math.log10(bass_before['volume'])),
        pan=bass_before['pan'])
    bass_after_restore = adapter.read_track(adapter.observe_session(), bass.guid)
    if (not math.isclose(bass_after_restore['volume'], bass_before['volume'], rel_tol=1e-8, abs_tol=1e-12)
            or not math.isclose(bass_after_restore['pan'], bass_before['pan'], rel_tol=0, abs_tol=1e-9)):
        raise RuntimeError('reversible mixer probe did not restore the disposable baseline')
    record('mixer_probe', {'set': test_mix, 'restore': restored_mix,
                           'readback': bass_after_restore})

    import_path = Path(manifest['import_tone']['path'])
    imported = adapter.import_stem(session, keys.guid, import_path,
                                   position_sec=float(manifest['import_position_sec']))
    imported_readback = adapter.read_stem(adapter.observe_session(), keys.guid, imported['item_guid'])
    record('stem_import', {'result': imported, 'readback': imported_readback})

    print('\nManual handoff on the disposable REAPER project:')
    manual_handoff = gate.manual_handoff(
        'Move Bass to about -2.99 dB, keeping pan at -0.2. On Keys, move the existing '
        'envelope point at 2.0 seconds to about -28 dB; preserve its existing 1s and 3s points.')
    manual_focus = manual_handoff['focus_after']
    session = adapter.observe_session()
    bass_manual = dict(adapter.read_track(session, bass.guid))
    keys_manual = dict(adapter.read_volume_envelope(session, keys.guid, start_sec=1, end_sec=3))
    record('manual_changes_observed', {'focus_after_handoff': manual_focus,
                                        'bass': bass_manual, 'keys_envelope': keys_manual})
    if not math.isclose(bass_manual['volume'], 10 ** (-2.99 / 20), rel_tol=0.03, abs_tol=0.01):
        raise RuntimeError(f'Bass fader readback is not near -2.99 dB: {bass_manual}')
    if not math.isclose(bass_manual['pan'], -0.2, rel_tol=0, abs_tol=0.02):
        raise RuntimeError(f'Bass pan readback differs from the handoff target: {bass_manual}')
    if keys_manual['points'] == [
            point for point in keys_before['points']
            if 1 <= point['time_sec'] <= 3]:
        raise RuntimeError('Keys envelope readback shows no manual edit')
    boundary1 = next((point for point in keys_manual['points'] if abs(point['time_sec'] - 1) < 1e-6), None)
    boundary3 = next((point for point in keys_manual['points'] if abs(point['time_sec'] - 3) < 1e-6), None)
    if boundary1 is None or boundary3 is None:
        raise RuntimeError('Keys envelope needs exact boundary points at one and three seconds')
    midpoint = next((point for point in keys_manual['points']
                     if abs(point['time_sec'] - 2.0) < 1e-6), None)
    if midpoint is None or midpoint['silent'] or not math.isclose(
            midpoint['gain_db'], -28.0, rel_tol=0, abs_tol=5.0):
        raise RuntimeError(f'Keys manual point at 2s is not near -28 dB: {midpoint}')
    record('manual_changes_accepted', {'bass': bass_manual, 'keys_envelope': keys_manual})

    def point_db(point: dict[str, Any]) -> dict[str, Any]:
        return {'time_sec': point['time_sec'],
                'silent': point['silent']} if point['silent'] else {
                    'time_sec': point['time_sec'], 'gain_db': point['gain_db']}

    patch_points = [point_db(boundary1), {'time_sec': 2.0, 'gain_db': -12.0}, point_db(boundary3)]
    patch = adapter.patch_volume_envelope(session, keys.guid, keys_manual, patch_points)
    patched_read = adapter.read_volume_envelope(adapter.observe_session(), keys.guid,
                                                start_sec=1, end_sec=3)
    if patched_read['points'] != patch['observed']['points']:
        raise RuntimeError('independent envelope readback differs from the applied proposal')
    undone = adapter.undo_volume_patch(adapter.observe_session(), keys.guid, patch)
    if undone['observed']['points'] != keys_manual['points']:
        raise RuntimeError('scoped envelope undo did not restore the manual points')
    record('bounded_envelope_patch', {'patch': patch, 'independent_read': patched_read,
                                     'undo': undone})

    # Change the observed target once, then prove the older proposal is rejected.
    conflict_baseline = adapter.read_volume_envelope(adapter.observe_session(), keys.guid,
                                                     start_sec=1, end_sec=3)
    endpoints = [point_db(boundary1), {'time_sec': 2.0, 'gain_db': -15.0}, point_db(boundary3)]
    intervening = adapter.patch_volume_envelope(session, keys.guid, conflict_baseline, endpoints)
    stale_rejected = False
    try:
        adapter.patch_volume_envelope(session, keys.guid, conflict_baseline,
                                      [point_db(boundary1), {'time_sec': 2.0, 'gain_db': -6.0},
                                       point_db(boundary3)])
    except ProposalConflict as conflict:
        stale_rejected = True
        conflict_text = str(conflict)
    else:
        raise RuntimeError('stale envelope proposal unexpectedly applied')
    conflict_read = adapter.read_volume_envelope(adapter.observe_session(), keys.guid,
                                                 start_sec=1, end_sec=3)
    if conflict_read['points'] != intervening['observed']['points']:
        raise RuntimeError('stale proposal changed the intervening envelope edit')
    conflict_undo = adapter.undo_volume_patch(adapter.observe_session(), keys.guid, intervening)
    if conflict_undo['observed']['points'] != keys_manual['points']:
        raise RuntimeError('conflict cleanup did not restore the manual envelope')
    record('stale_conflict', {'rejected': stale_rejected, 'error': conflict_text,
                              'intervening_readback': conflict_read, 'undo': conflict_undo})

    render_wav = root / 'mix.wav'
    set_render = gate.step('bridge.project.set_render', lambda: bridge.send(
        'project.set_render', {'path': str(render_wav)}, timeout=args.request_timeout,
        resource_path=resource))
    if set_render.get('ok') is not True or set_render.get('result', {}).get('readback') != str(render_wav):
        raise RuntimeError('render path did not read back exactly')
    saved = gate.step('bridge.project.save.before_replacement', lambda: bridge.send(
        'project.save', {'path': str(project)}, timeout=args.request_timeout,
        resource_path=resource))
    if saved.get('ok') is not True or not project.is_file():
        raise RuntimeError('native project save did not complete')
    record('saved_manual_state', {'reply': saved, 'project_sha256': sha256(project)})

    drums_baseline = adapter.read_stem(adapter.observe_session(), drums.guid, drum_layout['item_guid'])
    replacement = adapter.replace_stem(adapter.observe_session(), drums.guid, drums_baseline,
                                       Path(manifest['replacement_tone']['path']))
    independent = adapter.read_stem(adapter.observe_session(), drums.guid, drum_layout['item_guid'])
    if independent['source_path'] != replacement['observed']['source_path']:
        raise RuntimeError('independent Drums readback differs from replacement receipt')
    bass_after_replace = adapter.read_track(adapter.observe_session(), bass.guid)
    keys_after_replace = adapter.read_volume_envelope(adapter.observe_session(), keys.guid,
                                                      start_sec=1, end_sec=3)
    if (not math.isclose(bass_after_replace['volume'], bass_manual['volume'], rel_tol=1e-8)
            or not math.isclose(bass_after_replace['pan'], bass_manual['pan'], abs_tol=1e-8)
            or keys_after_replace['points'] != keys_manual['points']):
        raise RuntimeError('part replacement changed the manually edited Bass or Keys state')
    record('part_replacement', {'receipt': replacement, 'drums_readback': independent,
                                'bass_preserved': bass_after_replace,
                                'keys_preserved': keys_after_replace})

    saved = gate.step('bridge.project.save.after_replacement', lambda: bridge.send(
        'project.save', {'path': str(project)}, timeout=args.request_timeout,
        resource_path=resource))
    if saved.get('ok') is not True or not project.is_file():
        raise RuntimeError('final project save did not complete')
    before_reopen_hash = sha256(project)
    reopen_script = root / 'a01-close-reopen.lua'
    reopen_marker = root / 'a01-close-reopen.txt'
    if reopen_marker.exists() or reopen_script.exists():
        raise FileExistsError('native reopen evidence path already exists')
    reopen_script.write_text(
        'local expected = ' + json.dumps(str(project)) + '\n'
        + 'local marker = ' + json.dumps(str(reopen_marker)) + '\n'
        + 'local function write(s) local f=assert(io.open(marker,"a")); f:write(s,"\\n"); f:close() end\n'
        + 'local _, path = reaper.EnumProjects(-1, "")\n'
        + 'if path ~= expected then write("refused_wrong_project=" .. tostring(path)); return end\n'
        + 'if reaper.IsProjectDirty(0) or reaper.GetPlayState() ~= 0 then write("refused_dirty_or_playing"); return end\n'
        + 'local count, i = 0, 0; while reaper.EnumProjects(i, "") do count=count+1; i=i+1 end\n'
        + 'if count ~= 1 then write("refused_project_tab_count=" .. count); return end\n'
        + 'write("close_begin=" .. path)\n'
        + 'reaper.Main_OnCommand(40859, 0)\n'
        + 'reaper.Main_openProject(expected)\n'
        + 'local _, reopened = reaper.EnumProjects(-1, "")\n'
        + 'write("reopened=" .. tostring(reopened == expected))\n', encoding='utf-8')
    reopen = gate.step('close and freshly reopen disposable RPP', lambda: subprocess.run(
        [str(REAPER), '-cfgfile', str(resource / 'reaper.ini'), '-nonewinst', '-noactivate',
         str(reopen_script)], capture_output=True, text=True, timeout=25, check=True))
    if not reopen_marker.is_file() or 'reopened=true' not in reopen_marker.read_text():
        raise RuntimeError(f'native close/reopen marker missing or failed: {reopen_marker}')
    process_after = gate.step('isolated profile process identity after reopen',
                              lambda: _profile_process(resource))
    session = adapter.observe_session()
    if session.path != project or process_after['pid'] != process['pid']:
        raise RuntimeError('fresh reopen changed the session path or REAPER process identity')
    if session.token == evidence['steps']['session_before']['token']:
        raise RuntimeError('session binding token did not change across fresh tab close/reopen')
    drums_final = adapter.read_stem(session, drums.guid, drum_layout['item_guid'])
    bass_final = adapter.read_track(adapter.observe_session(), bass.guid)
    keys_final = adapter.read_volume_envelope(adapter.observe_session(), keys.guid,
                                              start_sec=1, end_sec=3)
    if (drums_final['source_path'] != independent['source_path']
            or not math.isclose(bass_final['volume'], bass_manual['volume'], rel_tol=1e-8)
            or keys_final['points'] != keys_manual['points']
            or sha256(project) != before_reopen_hash):
        raise RuntimeError('save/reopen readback differs from the accepted disposable state')
    record('save_reopen', {'returncode': reopen.returncode, 'stderr': reopen.stderr[-1000:],
                           'project_sha256': before_reopen_hash,
                           'session': _session_identity(session), 'drums': drums_final,
                           'bass': bass_final, 'keys_envelope': keys_final})

    rendered = gate.step('headless stereo export', lambda:
        _render(project, render_resource, args.render_timeout))
    audio = gate.step('mix and aligned stem fidelity check', lambda: _analyze_exports(
        args.controller, project, render_resource / 'reaper.ini', render_wav))
    evidence.update(ended_at_utc=utc_now(), ok=True, final_project_sha256=sha256(project),
                    render=rendered, export_analysis=audio,
                    qualification_note='Disposable Gate A workflow only; not Gate C musical acceptance.')
    _new_json(report, evidence)
    manifest['state'] = 'completed'
    manifest['completed_at_utc'] = utc_now()
    manifest['evidence'] = str(report)
    _new_json(root / 'a01-manifest-completed.json', manifest)
    return evidence


def _render(project: Path, resource: Path, timeout: float) -> dict[str, Any]:
    if not 10 <= timeout <= 60:
        raise ValueError('render timeout must be 10..60 seconds')
    started = time.monotonic()
    process = subprocess.Popen(
        [str(REAPER), '-cfgfile', str(resource / 'reaper.ini'), '-renderproject', str(project)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=3)
        raise TimeoutError(
            f'render timed out; pid={process.pid}, elapsed_sec={time.monotonic() - started:.3f}, '
            f'returncode={process.returncode}, process_reaped={process.poll() is not None}, '
            f'stdout={stdout[-1000:]!r}, stderr={stderr[-1000:]!r}') from error
    wav_path = Path(re.search(r'(?m)^\s*RENDER_FILE "([^"]+)"',
                              project.read_text(encoding='utf-8')).group(1))
    if process.returncode != 0 or not wav_path.is_file() or wav_path.stat().st_size == 0:
        raise RuntimeError(f'render failed: pid={process.pid}, returncode={process.returncode}, stderr={stderr[-1000:]}')
    with wave.open(str(wav_path), 'rb') as wav:
        info = {'channels': wav.getnchannels(), 'sample_rate': wav.getframerate(),
                'sample_width_bytes': wav.getsampwidth(), 'frames': wav.getnframes(),
                'duration_sec': wav.getnframes() / wav.getframerate()}
    info.update({'pid': process.pid, 'returncode': process.returncode,
                 'elapsed_sec': round(time.monotonic() - started, 3),
                 'process_reaped': process.poll() is not None,
                 'stdout': stdout[-1000:], 'stderr': stderr[-1000:],
                 'path': str(wav_path), 'bytes': wav_path.stat().st_size,
                 'sha256': sha256(wav_path)})
    if info['channels'] != 2:
        raise RuntimeError('stereo mix export is required')
    return info


def _analyze_exports(controller: Path, project: Path, cfgfile: Path, mix: Path) -> dict[str, Any]:
    script = Path(__file__).with_name('reaper_export_stems.py')
    result = subprocess.run(
        [sys.executable, str(script), '--source', str(project),
         '--cfgfile', str(cfgfile), '--mix', str(mix)],
        env={**os.environ, 'PYTHONPATH': str(controller / 'src') + os.pathsep + os.environ.get('PYTHONPATH', '')},
        capture_output=True, text=True, timeout=120, check=True)
    parsed = json.loads(result.stdout)
    if not parsed.get('ok'):
        raise RuntimeError('mix/stem fidelity qualification failed')
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('prepare', help='copy the fixture and media into a new disposable run root')
    prepare.add_argument('--source-project', required=True, type=Path)
    prepare.add_argument('--root', required=True, type=Path)
    profile = sub.add_parser('prepare-profile', help='install bridge and protected license in new isolated profiles')
    profile.add_argument('--root', required=True, type=Path)
    profile.add_argument('--controller', required=True, type=Path)
    profile.add_argument('--license-source', required=True, type=Path)
    focus_check = sub.add_parser('focus-check', help='compile and run the read-only frontmost-app probe')
    focus_check.add_argument('--root', required=True, type=Path)
    run = sub.add_parser('run', help='run against the exact open disposable profile and project')
    run.add_argument('--root', required=True, type=Path)
    run.add_argument('--controller', required=True, type=Path)
    run.add_argument('--resource', required=True, type=Path)
    run.add_argument('--request-timeout', type=float, default=5.0)
    run.add_argument('--render-timeout', type=float, default=30.0)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            result = prepare_fixture(args.source_project, args.root)
        elif args.command == 'prepare-profile':
            result = prepare_profiles(args.root, args.controller, args.license_source)
        elif args.command == 'focus-check':
            root = Path(args.root).resolve(strict=True)
            probe = FocusProbe(root)
            probe.build()
            result = probe.read()
            if result['bundle_id'] == REAPER_BUNDLE_ID or result['bundle_id'] in NON_USER_FRONTMOST_BUNDLE_IDS:
                raise RuntimeError(f"frontmost app is not eligible for A01: {result['bundle_id']}")
        else:
            result = run_qualification(args)
        print(json.dumps(plain(result), indent=2, sort_keys=True))
        return 0
    except Exception as error:
        if getattr(args, 'command', None) == 'run':
            try:
                root = Path(os.path.abspath(args.root))
                if root.is_dir() and root.is_relative_to(BASE) and not root.is_symlink():
                    journal = root / 'a01-focus.jsonl'
                    manifest_path = root / 'a01-manifest-profile.json'
                    manifest = (json.loads(manifest_path.read_text(encoding='utf-8'))
                                if manifest_path.is_file() else {})
                    project = Path(manifest['project']) if manifest.get('project') else None
                    failure = {
                        'schema': 'llm-studio.reaper-gate-a01-failure.v1',
                        'at_utc': utc_now(), 'root': str(root), 'ok': False,
                        'error': f'{type(error).__name__}: {error}',
                        'traceback': traceback.format_exc(),
                        'focus_journal': str(journal) if journal.is_file() else None,
                        'focus_journal_sha256': sha256(journal) if journal.is_file() else None,
                        'project': str(project) if project else None,
                        'project_sha256_at_failure':
                            sha256(project) if project and project.is_file() else None,
                        'effects_and_receipts': 'See durable a01-focus.jsonl started/finished and qualification-checkpoint events.',
                    }
                    _new_json(root / 'a01-failure.json', failure)
            except Exception as evidence_error:
                print(f'Could not write supplemental failure record: {type(evidence_error).__name__}: {evidence_error}',
                      file=sys.stderr)
        print(json.dumps({'ok': False, 'error': f'{type(error).__name__}: {error}'}, indent=2),
              file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
