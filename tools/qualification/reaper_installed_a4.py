"""One bounded installed-file-drop stem replacement on a pre-opened A4 copy.

This helper never starts REAPER or chooses/closes tabs. Open a unique disposable
RPP in a fresh isolated profile first. The adapter does not enumerate other
tabs, so the caller must ensure this path is unique and the tab is clean.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import struct
import sys
import wave
from datetime import datetime, timezone
from typing import Any, Mapping

from llm_studio import bootstrap
from llm_studio.reaper import ReaperAdapterError, ReaperStudioAdapter, Session, Track


BASE = Path('/private/tmp/llm-studio-reaper')
EXPECTED_TRACKS = ('Keys', 'Bass', 'Drums')
TRACK_BLOCK = re.compile(r'(?ms)^  <TRACK (\{[^}\r\n]+\})[^\r\n]*\r?\n(.*?)^  >$')
ITEM_BLOCK = re.compile(r'(?ms)^    <ITEM\s*\r?\n(.*?)^    >$')


def project_layout(path: Path) -> list[dict[str, Any]]:
    """Read saved track/item GUIDs needed to bind the live snapshot safely."""
    text = path.read_text(encoding='utf-8')
    layout = []
    for match in TRACK_BLOCK.finditer(text):
        guid, block = match.groups()
        name = re.search(r'(?m)^    NAME (.+)$', block)
        volpan = re.search(r'(?m)^    VOLPAN ([^\s]+) ([^\s]+)', block)
        fx_names = re.findall(r'(?m)^\s*<VST "([^"]+)"', block)
        items = ITEM_BLOCK.findall(block)
        if not name:
            raise ValueError('RPP track is missing its name')
        if len(items) != 1:
            raise ValueError(f'{name.group(1)} must contain exactly one media item')
        item_guid = re.search(r'(?m)^      IGUID (\{[^}]+\})$', items[0])
        if not item_guid:
            raise ValueError(f'{name.group(1)} item is missing its GUID')
        position = re.search(r'(?m)^      POSITION ([^\s]+)$', items[0])
        length = re.search(r'(?m)^      LENGTH ([^\s]+)$', items[0])
        if not position or not length:
            raise ValueError(f'{name.group(1)} item is missing position or length')
        if not volpan:
            raise ValueError(f'{name.group(1)} track is missing VOLPAN')
        layout.append({'guid': guid, 'name': name.group(1),
                       'volume': float(volpan.group(1)), 'pan': float(volpan.group(2)),
                       'fx': fx_names,
                       'item_guid': item_guid.group(1),
                       'position_sec': float(position.group(1)),
                       'length_sec': float(length.group(1))})
    if tuple(item['name'] for item in layout) != EXPECTED_TRACKS:
        raise ValueError(f'expected tracks {EXPECTED_TRACKS}, found '
                         f'{tuple(item["name"] for item in layout)}')
    if len({item['guid'] for item in layout}) != len(layout):
        raise ValueError('RPP contains duplicate track GUIDs')
    return layout


def _validate_sha256(value: str, label: str) -> str:
    if not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError(f'{label} must be a lowercase SHA256 hex digest')
    return value


def _is_exact_zero(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value == 0.0


def _require_sha256_match(actual: str, expected: str, label: str) -> None:
    _validate_sha256(actual, f'actual {label} SHA256')
    _validate_sha256(expected, f'expected {label} SHA256')
    if actual != expected:
        raise ValueError(f'{label} SHA256 differs from caller-approved baseline')


def _validate_saved_bass(track: Mapping[str, Any]) -> None:
    if (track.get('name') != 'Bass'
            or not _is_exact_zero(track.get('volume'))
            or not math.isclose(track.get('pan', math.nan), -0.2, rel_tol=0, abs_tol=1e-9)
            or not any('ReaEQ' in name for name in track.get('fx', []))):
        raise ValueError('saved Bass baseline must be silent (linear gain 0), pan -0.2, with ReaEQ')


def _validate_live_bass(state: Mapping[str, Any]) -> None:
    fx = state.get('fx')
    if fx == {}:
        fx = []
    if (not _is_exact_zero(state.get('volume'))
            or not math.isclose(state.get('pan', math.nan), -0.2, rel_tol=0, abs_tol=1e-9)
            or not isinstance(fx, list)
            or not any(isinstance(effect, Mapping) and 'ReaEQ' in effect.get('name', '')
                       for effect in fx)):
        raise ValueError('live Bass must read silent (linear gain 0), pan -0.2, with ReaEQ')


def write_replacement_tone(path: Path, duration_sec: float, *, rate: int = 48000,
                           frequency: int = 440, amplitude: int = 3700) -> dict[str, Any]:
    """Write a unique, mono PCM16 test stem with exactly the observed duration."""
    frames_float = duration_sec * rate
    frames = round(frames_float)
    if (not math.isfinite(duration_sec) or duration_sec <= 0
            or not math.isclose(frames_float, frames, rel_tol=0, abs_tol=1e-6)):
        raise ValueError('item duration is not an exact 48 kHz frame count')
    if path.exists() or path.is_symlink():
        raise FileExistsError(f'refusing to overwrite replacement fixture: {path}')
    samples = (round(amplitude * math.sin(2 * math.pi * frequency * i / rate))
               for i in range(frames))
    with path.open('xb') as raw:
        with wave.open(raw, 'wb') as output:
            output.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
            output.writeframes(b''.join(struct.pack('<h', sample) for sample in samples))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'path': str(path), 'sha256': digest, 'sample_rate': rate,
            'channels': 1, 'sample_width_bytes': 2, 'frames': frames,
            'duration_sec': frames / rate, 'frequency_hz': frequency,
            'amplitude': amplitude}


def _source_check(controller: Path) -> dict[str, str]:
    expected = (controller / 'src' / 'reaper_connector').resolve()
    spec = importlib.util.find_spec('reaper_connector')
    origin = Path(spec.origin).resolve() if spec and spec.origin else None
    if origin is None or not origin.is_relative_to(expected):
        raise RuntimeError(f'imported reaper_connector is outside supplied pinned checkout: {origin}')
    return {'expected_source': str(expected), 'imported_source': str(origin)}


def _new_output(path: Path, evidence: Mapping[str, Any]) -> None:
    if os.path.lexists(path):
        raise FileExistsError(f'refusing to overwrite evidence file: {path}')
    if not path.parent.is_dir():
        raise FileNotFoundError(f'evidence directory does not exist: {path.parent}')
    with path.open('x', encoding='utf-8') as stream:
        json.dump(evidence, stream, indent=2, sort_keys=True)
        stream.write('\n')


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if value is None or type(value) in (str, int, float, bool):
        return value
    return repr(value)


def _session_evidence(session: Session) -> dict[str, Any]:
    return {'id': session.id, 'token': session.token, 'path': str(session.path),
            'state_change_count': session.state_change_count,
            'tracks': [{'guid': track.guid, 'name': track.name, 'index': track.index}
                       for track in session.tracks]}


def _same_envelope(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    return (before.get('envelope_guid') == after.get('envelope_guid')
            and before.get('points') == after.get('points'))


def _same_bass(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    return all(before.get(key) == after.get(key) for key in ('volume', 'pan', 'fx'))


def _check_live_session(session: Session, expected_project: Path,
                        layout: list[dict[str, Any]]) -> dict[str, Track]:
    if session.path != expected_project:
        raise ValueError(f'active project differs: expected {expected_project}, observed {session.path}')
    if tuple(track.name for track in session.tracks) != EXPECTED_TRACKS:
        raise ValueError(f'active track names differ: {[track.name for track in session.tracks]}')
    if len(session.tracks) != len(layout):
        raise ValueError('active track count differs from saved project')
    bound = {}
    for actual, saved in zip(session.tracks, layout):
        if actual.guid != saved['guid'] or actual.name != saved['name']:
            raise ValueError(f'active track binding differs for {saved["name"]}')
        bound[actual.name] = actual
    return bound


def _independent_readback(adapter: ReaperStudioAdapter, previous: Session,
                          expected_project: Path, layout: list[dict[str, Any]],
                          drums: Track, item_guid: str) -> dict[str, Any]:
    fresh = adapter.observe_session()
    if (fresh.id, fresh.token, fresh.path) != (previous.id, previous.token, expected_project):
        raise ValueError('session identity changed during replacement')
    _check_live_session(fresh, expected_project, layout)
    return {'session': _session_evidence(fresh),
            'drums': _plain(adapter.read_stem(fresh, drums.guid, item_guid)),
            'bass': _plain(adapter.read_track(fresh, next(t.guid for t in fresh.tracks if t.name == 'Bass'))),
            'keys_envelope': _plain(adapter.read_volume_envelope(
                fresh, next(t.guid for t in fresh.tracks if t.name == 'Keys'),
                start_sec=0.0, end_sec=5.0))}


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.absolute()
    if os.path.lexists(output):
        raise FileExistsError(f'refusing to overwrite evidence file: {output}')
    if (not output.parent.is_dir() or output.parent != output.parent.resolve()
            or not output.parent.is_relative_to(BASE)):
        raise ValueError('evidence output parent must be a canonical existing directory under the disposable root')
    evidence: dict[str, Any] = {
        'ok': False, 'operation_passed': False, 'save_reopen_pending': True,
        'qualification_note': 'One installed replacement and independent readback only; save/reopen is separate.',
        'baseline_provenance': 'Expected hashes are caller-supplied from after-manual.json and producer confirmation; this helper verifies bytes and continuity only.',
        'observed_at_utc': datetime.now(timezone.utc).isoformat(),
        'replace_call_count': 0,
    }
    adapter = None
    session = None
    layout = None
    drums = None
    item_guid = None
    stem_info = None
    try:
        controller = args.controller.resolve(strict=True)
        raw_resource = args.resource.absolute()
        raw_project = args.project.absolute()
        resource = raw_resource.resolve(strict=True)
        project = raw_project.resolve(strict=True)
        if raw_resource != resource or raw_project != project:
            raise ValueError('resource and project paths must not contain symlinks')
        if not resource.is_dir() or not (resource / 'reaper.ini').is_file():
            raise ValueError('resource must be the selected isolated profile resource directory')
        if not (resource / 'Scripts/agent_bridge.lua').is_file():
            raise ValueError('installed agent_bridge.lua is missing from selected resource')
        if not (resource / 'Scripts/llm_studio_reaper.lua').is_file():
            raise ValueError('installed studio handler is missing from selected resource')
        if (not project.is_file() or project.suffix.lower() != '.rpp'
                or not project.is_relative_to(BASE)):
            raise ValueError('project must be a canonical saved RPP under the disposable REAPER root')
        if not 1 <= args.timeout_sec <= 10:
            raise ValueError('per-request timeout must be between 1 and 10 seconds')
        expected_project_hash = _validate_sha256(args.expected_project_sha256,
                                                 'expected project SHA256')
        expected_drums_hash = _validate_sha256(args.expected_drum_source_sha256,
                                                'expected Drums source SHA256')
        actual_project_hash = hashlib.sha256(project.read_bytes()).hexdigest()
        evidence['project_sha256'] = actual_project_hash
        evidence['expected_project_sha256'] = expected_project_hash
        evidence['expected_drum_source_sha256'] = expected_drums_hash
        _require_sha256_match(actual_project_hash, expected_project_hash, 'saved project')
        layout = project_layout(project)
        _validate_saved_bass(next(track for track in layout if track['name'] == 'Bass'))
        commit = bootstrap.validate_controller_checkout(controller)
        imported = _source_check(controller)
        from reaper_connector import bridge

        def send(operation: str, params: dict[str, Any]) -> dict[str, Any]:
            return bridge.send(operation, params, timeout=args.timeout_sec,
                               resource_path=resource)

        adapter = ReaperStudioAdapter(send)
        evidence['controller'] = {'checkout': str(controller), 'commit': commit, **imported}
        evidence['resource'] = str(resource)
        evidence['project_expected'] = str(project)
        session = adapter.observe_session()
        bound = _check_live_session(session, project, layout)
        evidence['session_before'] = _session_evidence(session)
        evidence['track_bindings'] = {name: track.guid for name, track in bound.items()}

        bass_track, keys_track, drums = bound['Bass'], bound['Keys'], bound['Drums']
        bass_before = dict(adapter.read_track(session, bass_track.guid))
        _validate_live_bass(bass_before)
        envelope_before = dict(adapter.read_volume_envelope(
            session, keys_track.guid, start_sec=0.0, end_sec=5.0))
        item_guids = {entry['name']: entry['item_guid'] for entry in layout}
        stems_before = {name: dict(adapter.read_stem(session, bound[name].guid, item_guids[name]))
                        for name in EXPECTED_TRACKS}
        for name, item in stems_before.items():
            saved = next(entry for entry in layout if entry['name'] == name)
            if (item['track_guid'] != saved['guid'] or item['item_guid'] != saved['item_guid']
                    or not math.isclose(item['position_sec'], saved['position_sec'], abs_tol=1e-9)
                    or not math.isclose(item['length_sec'], saved['length_sec'], abs_tol=1e-6)):
                raise ValueError(f'{name} live item differs from its saved RPP binding')
        baseline = stems_before['Drums']
        if baseline['channels'] != 1 or baseline['sample_rate'] != 48000:
            raise ValueError('Drums target must be mono 48 kHz before replacement')
        if not math.isclose(baseline['position_sec'], 0.0, abs_tol=1e-9):
            raise ValueError('Drums target must start at project time zero')
        frames = baseline['length_sec'] * 48000
        if not math.isclose(frames, round(frames), rel_tol=0, abs_tol=1e-6):
            raise ValueError('Drums item length is not representable at 48 kHz')

        old_source = Path(baseline['source_path'])
        if not old_source.is_file():
            raise ValueError(f'current Drums source is not readable for hash comparison: {old_source}')
        old_source_hash = hashlib.sha256(old_source.read_bytes()).hexdigest()
        evidence['current_drums_source_sha256'] = old_source_hash
        evidence['expected_drum_source_sha256'] = expected_drums_hash
        _require_sha256_match(old_source_hash, expected_drums_hash, 'current Drums source')
        replacement_source = project.parent / 'installed-a4-replacement-440hz.wav'
        stem_info = write_replacement_tone(replacement_source, baseline['length_sec'])
        if stem_info['sha256'] == old_source_hash:
            raise ValueError('replacement fixture is byte-identical to current Drums source')
        evidence.update({'stems_before': _plain(stems_before),
                         'bass_before': _plain(bass_before),
                         'keys_envelope_before': _plain(envelope_before),
                         'replacement_source': stem_info,
                         'replacement_differs_from_current_source': True,
                         'transport_requirement': 'The installed handler checks stopped transport atomically in replace_stem; a refusal is not retried.'})
        item_guid = baseline['item_guid']
        evidence['replace_call_count'] = 1
        try:
            result = adapter.replace_stem(session, drums.guid, baseline, replacement_source)
            evidence['replace_result'] = _plain(result)
            evidence['operation_passed'] = True
        except Exception as operation_error:
            evidence['replace_error'] = f'{type(operation_error).__name__}: {operation_error}'
            evidence['operation_outcome'] = 'uncertain; one fresh readback will reconcile, no retry'

        try:
            independent = _independent_readback(adapter, session, project, layout, drums, item_guid)
            evidence['independent_readback'] = independent
            observed = independent['drums']
            expected_asset = project.parent / 'media' / f"{stem_info['sha256']}.wav"
            target_matches = (observed['source_path'] == str(expected_asset)
                              and observed['item_guid'] == baseline['item_guid']
                              and observed['take_guid'] == baseline['take_guid']
                              and observed['position_sec'] == baseline['position_sec']
                              and observed['length_sec'] == baseline['length_sec']
                              and observed['channels'] == baseline['channels']
                              and observed['sample_rate'] == baseline['sample_rate'])
            preserved = (_same_bass(bass_before, independent['bass'])
                         and _same_envelope(envelope_before, independent['keys_envelope']))
            result_match = (evidence.get('replace_result', {}).get('observed', {}).get('source_path')
                            == observed['source_path'])
            evidence['independent_checks'] = {
                'same_session_identity': True,
                'target_binding_and_format_preserved': target_matches,
                'replace_result_matches_independent_source': result_match,
                'bass_gain_pan_fx_preserved': _same_bass(bass_before, independent['bass']),
                'keys_envelope_preserved': _same_envelope(envelope_before, independent['keys_envelope']),
                'stopped_transport': 'accepted by installed handler at mutation boundary' if evidence['operation_passed'] else 'not established',
            }
            evidence['ok'] = bool(evidence['operation_passed'] and target_matches
                                  and result_match and preserved)
            evidence['operation_outcome'] = ('verified' if evidence['ok'] else
                'reconciled after one attempt; inspect recorded state and do not retry')
        except Exception as readback_error:
            evidence['independent_readback_error'] = f'{type(readback_error).__name__}: {readback_error}'
            evidence['operation_outcome'] = 'uncertain; independent readback failed; do not retry'
    except Exception as error:
        evidence['error'] = f'{type(error).__name__}: {error}'
    _new_output(output, evidence)
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--controller', required=True, type=Path,
                        help='clean checkout at the pinned controller commit')
    parser.add_argument('--resource', required=True, type=Path,
                        help='exact isolated profile resource directory')
    parser.add_argument('--project', required=True, type=Path,
                        help='unique disposable RPP already open in the isolated REAPER profile')
    parser.add_argument('--expected-project-sha256', required=True,
                        help='caller-approved SHA256 of the saved RPP bytes')
    parser.add_argument('--expected-drum-source-sha256', required=True,
                        help='caller-approved SHA256 of the current Drums media source')
    parser.add_argument('--output', required=True, type=Path,
                        help='new JSON evidence path in an existing disposable directory')
    parser.add_argument('--timeout-sec', type=float, default=5.0,
                        help='bounded timeout for each file-drop request (1..10 seconds)')
    args = parser.parse_args(argv)
    try:
        evidence = run(args)
    except Exception as error:
        print(json.dumps({'ok': False, 'error': f'{type(error).__name__}: {error}'}, indent=2))
        return 1
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
