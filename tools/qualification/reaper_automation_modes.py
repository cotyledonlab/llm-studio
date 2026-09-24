#!/usr/bin/env python3
"""Qualify adapter automation-mode observation on an active disposable REAPER tab.

The script does not open or select projects. It forwards uniquely named native
ReaScripts to the explicitly selected running profile to set/read mode state;
all envelope reads and the single bounded patch use the installed adapter.
The requested project must already be open, saved, unique in that profile, and
stopped. The mode-1 patch remains in this disposable project.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from typing import Any

from llm_studio import bootstrap
from llm_studio.reaper import ReaperStudioAdapter


BASE = Path('/private/tmp/llm-studio-reaper')
REAPER = Path('/Applications/REAPER.app/Contents/MacOS/REAPER')
MODE_NAMES = ('Trim/Read', 'Read', 'Touch', 'Write', 'Latch', 'Latch Preview')


def _new_json(path: Path, value: Any) -> None:
    if os.path.lexists(path):
        raise FileExistsError(f'refusing to overwrite {path}')
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


def _source_check(controller: Path) -> dict[str, str]:
    expected = (controller / 'src' / 'reaper_connector').resolve()
    spec = importlib.util.find_spec('reaper_connector')
    origin = Path(spec.origin).resolve() if spec and spec.origin else None
    if origin is None or not origin.is_relative_to(expected):
        raise RuntimeError(f'reaper_connector import {origin} is outside pinned checkout {expected}')
    return {'expected_source': str(expected), 'imported_source': str(origin)}


def _native_lua(project: Path, resource: Path, guid: str, mode: int | None,
                report: Path, chunk_path: Path) -> str:
    # Values are encoded as Lua string literals by JSON's compatible quoting.
    mode_value = 'nil' if mode is None else str(mode)
    return f'''local c={{project={json.dumps(str(project))},resource={json.dumps(str(resource))},guid={json.dumps(guid)},mode={mode_value},report={json.dumps(str(report))},chunk={json.dumps(str(chunk_path))}}}
local function out(path,text) local f=assert(io.open(path,'wb')); f:write(text); f:close() end
local project,path=reaper.EnumProjects(-1,'')
assert(path==c.project,'active project path differs')
assert(reaper.GetResourcePath()==c.resource,'resource path differs')
assert(reaper.GetPlayState()==0,'transport is not stopped')
local matching_tabs,index=0,0
while true do
  local tab,tab_path=reaper.EnumProjects(index,'')
  if not tab then break end
  if tab_path==c.project then matching_tabs=matching_tabs+1; assert(tab==project,'target path open in another tab') end
  index=index+1; assert(index<=1000,'project tab enumeration exceeded bound')
end
assert(matching_tabs==1,'target project path must be unique among open tabs')
local track
for i=0,reaper.CountTracks(project)-1 do
  local t=reaper.GetTrack(project,i)
  if reaper.GetTrackGUID(t)==c.guid then track=t end
end
assert(track,'Keys GUID not found')
local _,name=reaper.GetSetMediaTrackInfo_String(track,'P_NAME','',false)
assert(name=='Keys','bound track is not Keys')
local env=reaper.GetTrackEnvelopeByChunkName(track,'<VOLENV2')
assert(env,'Keys volume envelope missing')
if c.mode~=nil then reaper.SetTrackAutomationMode(track,c.mode) end
local _,chunk=reaper.GetEnvelopeStateChunk(env,'',false)
local evidence={{project=path,resource=reaper.GetResourcePath(),guid=reaper.GetTrackGUID(track),name=name,
  play_state=reaper.GetPlayState(),mode=reaper.GetTrackAutomationMode(track),
  global_override=reaper.GetGlobalAutomationOverride(),chunk_bytes=#chunk}}
assert(c.mode==nil or evidence.mode==c.mode,'native mode readback differs')
out(c.chunk,chunk)
out(c.report,assert((function()
  local fields={{evidence.project,evidence.resource,evidence.guid,evidence.name,
    tostring(evidence.play_state),tostring(evidence.mode),tostring(evidence.global_override),tostring(evidence.chunk_bytes)}}
  return table.concat(fields,'\\n')..'\\n'
end)()))
'''


def _forward(profile: Path, script: Path, report: Path, timeout: float) -> dict[str, Any]:
    subprocess.run([str(REAPER), '-cfgfile', str(profile), '-nonewinst', '-noactivate', str(script)],
                   check=True, timeout=timeout, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if report.is_file():
            fields = report.read_text(encoding='utf-8').splitlines()
            if len(fields) != 8:
                raise RuntimeError(f'incomplete native report {report}')
            return {'project': fields[0], 'resource': fields[1], 'guid': fields[2],
                    'name': fields[3], 'play_state': int(fields[4]), 'mode': int(fields[5]),
                    'global_override': int(fields[6]), 'chunk_bytes': int(fields[7])}
        time.sleep(.05)
    raise TimeoutError(f'native forwarded ReaScript produced no report: {report}')


def run(args: argparse.Namespace) -> dict[str, Any]:
    project = args.project.resolve(strict=True)
    profile = args.cfgfile.resolve(strict=True)
    resource = args.resource.resolve(strict=True)
    controller = args.controller.resolve(strict=True)
    output = args.output.absolute()
    if os.path.lexists(output):
        raise FileExistsError(f'refusing to overwrite evidence file: {output}')
    if not project.is_relative_to(BASE) or project.suffix.lower() != '.rpp':
        raise ValueError(f'project must be a saved disposable RPP under {BASE}')
    if profile.name != 'reaper.ini' or profile.parent != resource:
        raise ValueError('cfgfile must be resource/reaper.ini and resource must be that exact profile directory')
    if not args.keys_guid.startswith('{') or not args.keys_guid.endswith('}'):
        raise ValueError('--keys-guid must be the exact saved Keys track GUID')
    if not output.parent.is_dir() or output.parent.resolve() != output.parent or not output.parent.is_relative_to(BASE):
        raise ValueError('output parent must be an existing canonical directory under the disposable root')
    if args.timeout <= 0:
        raise ValueError('--timeout must be positive')
    commit = bootstrap.validate_controller_checkout(controller)
    source = _source_check(controller)
    from reaper_connector import bridge

    adapter = ReaperStudioAdapter(lambda op, params: bridge.send(
        op, params, timeout=args.timeout, resource_path=resource))
    session = adapter.observe_session()
    if session.path != project or not session.tracks:
        raise ValueError(f'active session must be the exact requested project; observed {session.path}')
    keys = [track for track in session.tracks if track.guid == args.keys_guid and track.name == 'Keys']
    if len(keys) != 1:
        raise ValueError('the exact Keys GUID must identify one active Keys track')
    keys_guid = keys[0].guid
    baseline = adapter.read_volume_envelope(session, keys_guid,
                                            start_sec=args.start_sec, end_sec=args.end_sec)
    baseline_points = baseline['points']
    if not any(point['time_sec'] == args.start_sec for point in baseline_points) or not any(
            point['time_sec'] == args.end_sec for point in baseline_points):
        raise ValueError('bounded patch endpoints must already exist in the Keys envelope')
    original_mode = baseline['automation_mode']
    if type(original_mode) is not int or original_mode not in range(6):
        raise ValueError(f'unsupported original automation mode: {original_mode!r}')
    original_override = baseline['global_override']
    if type(original_override) is not int:
        raise ValueError('adapter did not return an integer global automation override')

    root = Path(tempfile.mkdtemp(prefix='automation-modes-', dir=BASE))
    mode_evidence = []
    chunk_hashes = []
    session_id, token = session.id, session.token

    def native(mode: int | None, label: str) -> dict[str, Any]:
        stem = f'{label}-{time.time_ns()}'
        report, chunk, script = root / f'{stem}.txt', root / f'{stem}.chunk', root / f'{stem}.lua'
        script.write_text(_native_lua(project, resource, keys_guid, mode, report, chunk), encoding='utf-8')
        result = _forward(profile, script, report, args.timeout)
        if (result['project'], result['resource'], result['guid'], result['name'], result['play_state']) != (
                str(project), str(resource), keys_guid, 'Keys', 0):
            raise RuntimeError(f'native exact project/profile/track/stopped proof failed: {result}')
        result['chunk_sha256'] = hashlib.sha256(chunk.read_bytes()).hexdigest()
        return result

    try:
        for mode, name in enumerate(MODE_NAMES):
            native_before = native(mode, f'mode-{mode}')
            fresh = adapter.observe_session()
            if (fresh.id, fresh.token, fresh.path) != (session_id, token, project):
                raise RuntimeError('adapter session identity changed during mode observations')
            state = adapter.read_volume_envelope(fresh, keys_guid,
                                                 start_sec=args.start_sec, end_sec=args.end_sec)
            native_after = native(None, f'mode-confirm-{mode}')
            if native_after['mode'] != mode:
                raise RuntimeError(f'native mode changed during adapter read in {name}: {native_after["mode"]}')
            if (state.get('automation_mode'), state.get('global_override')) != (
                    mode, native_after['global_override']):
                raise RuntimeError(f'adapter mode/override differs from native in {name}: {state}')
            if state['points'] != baseline_points or native_before['chunk_sha256'] != native_after['chunk_sha256']:
                raise RuntimeError(f'envelope lane changed while observing {name}')
            if native_after['global_override'] != original_override:
                raise RuntimeError(f'global override changed while observing {name}')
            mode_evidence.append({'mode': mode, 'name': name, 'adapter_mode': state['automation_mode'],
                                  'global_override': state['global_override'],
                                  'native_mode': native_after['mode'],
                                  'chunk_sha256': native_after['chunk_sha256'],
                                  'points_unchanged': True})
            chunk_hashes.append(native_after['chunk_sha256'])

        native(original_mode, 'restore-original-before-patch')
        fresh = adapter.observe_session()
        restored = adapter.read_volume_envelope(fresh, keys_guid,
                                                start_sec=args.start_sec, end_sec=args.end_sec)
        if restored['automation_mode'] != original_mode or restored['global_override'] != original_override:
            raise RuntimeError('original mode/global override was not restored')

        native(1, 'prepare-mode-1-patch')
        patch_base = adapter.read_volume_envelope(adapter.observe_session(), keys_guid,
                                                  start_sec=args.start_sec, end_sec=args.end_sec)
        if patch_base['automation_mode'] != 1 or patch_base['global_override'] != original_override:
            raise RuntimeError('mode-1 patch precondition or global override differs')
        by_time = {point['time_sec']: point for point in patch_base['points']}
        midpoint = (args.start_sec + args.end_sec) / 2
        if midpoint in by_time:
            midpoint = (args.start_sec * 2 + args.end_sec) / 3
        if midpoint in by_time or not args.start_sec < midpoint < args.end_sec:
            raise ValueError('cannot choose a unique interior point for the bounded patch')
        start, end = by_time[args.start_sec], by_time[args.end_sec]
        points = [
            {'time_sec': args.start_sec, 'gain_db': start['gain_db']} if not start['silent'] else
            {'time_sec': args.start_sec, 'silent': True},
            {'time_sec': midpoint, 'gain_db': args.patch_gain_db},
            {'time_sec': args.end_sec, 'gain_db': end['gain_db']} if not end['silent'] else
            {'time_sec': args.end_sec, 'silent': True},
        ]
        patch = adapter.patch_volume_envelope(adapter.observe_session(), keys_guid, patch_base, points)
        after_patch_native = native(None, 'after-mode-1-patch')
        after_patch = adapter.read_volume_envelope(adapter.observe_session(), keys_guid,
                                                   start_sec=args.start_sec, end_sec=args.end_sec)
        after_patch_read_native = native(None, 'after-adapter-mode-1-read')
        if (after_patch['automation_mode'], after_patch['global_override'], after_patch_native['mode'],
                after_patch_native['global_override'], after_patch_read_native['mode'],
                after_patch_read_native['global_override']) != (
                    1, original_override, 1, original_override, 1, original_override):
            raise RuntimeError('patch changed automation mode or global override')
        native(original_mode, 'restore-original-after-patch')
        final_native = native(None, 'verify-original-after-patch')
        final_session = adapter.observe_session()
        final_state = adapter.read_volume_envelope(final_session, keys_guid,
                                                   start_sec=args.start_sec, end_sec=args.end_sec)
        if (final_state['automation_mode'], final_state['global_override'], final_native['mode'],
                final_native['global_override']) != (original_mode, original_override, original_mode, original_override):
            raise RuntimeError('original mode/global override not restored after patch')
        if len(set(chunk_hashes)) != 1:
            raise RuntimeError('native envelope chunk changed across mode observation loop')
        evidence = {
            'ok': True, 'qualification': 'A06 automation mode observation and no hidden mode/override change',
            'observed_at_utc': datetime.now(timezone.utc).isoformat(),
            'controller': {'checkout': str(controller), 'commit': commit, **source},
            'project': str(project), 'profile_cfgfile': str(profile), 'resource': str(resource),
            'session': {'id': session_id, 'token': token}, 'keys_guid': keys_guid,
            'range_sec': [args.start_sec, args.end_sec], 'original_mode': original_mode,
            'global_override': original_override, 'modes': mode_evidence,
            'envelope_sha256_unchanged_across_mode_loop': chunk_hashes[0],
            'mode1_patch': {'midpoint_sec': midpoint, 'gain_db': args.patch_gain_db,
                            'adapter_mode_after': after_patch['automation_mode'],
                            'native_mode_after': after_patch_native['mode'],
                            'global_override_after': after_patch['global_override'],
                            'native_mode_after_adapter_read': after_patch_read_native['mode'],
                            'native_global_override_after_adapter_read': after_patch_read_native['global_override'],
                            'observed_points': after_patch['points'],
                            'patch_result_mode': patch['observed']['automation_mode']},
            'restored_mode_after_patch': final_state['automation_mode'],
            'final_native_mode': final_native['mode'],
        }
        _new_json(output, evidence)
        print(json.dumps(evidence, indent=2, sort_keys=True))
        return evidence
    except Exception as exc:
        restore_error = None
        try:
            native(original_mode, 'failure-restore-original')
        except Exception as restore_exc:
            restore_error = f'{type(restore_exc).__name__}: {restore_exc}'
        partial = {'ok': False, 'qualification': 'A06 automation mode observation',
                   'error': f'{type(exc).__name__}: {exc}', 'project': str(project),
                   'profile_cfgfile': str(profile), 'resource': str(resource),
                   'session': {'id': session_id, 'token': token}, 'modes_observed': mode_evidence,
                   'failure_restore_original_mode_error': restore_error}
        if not os.path.lexists(output):
            _new_json(output, partial)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--cfgfile', required=True, type=Path)
    parser.add_argument('--resource', required=True, type=Path)
    parser.add_argument('--controller', required=True, type=Path)
    parser.add_argument('--keys-guid', required=True)
    parser.add_argument('--start-sec', type=float, default=1.0)
    parser.add_argument('--end-sec', type=float, default=3.0)
    parser.add_argument('--patch-gain-db', type=float, default=-12.0)
    parser.add_argument('--timeout', type=float, default=12.0)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if not (0 <= args.start_sec < args.end_sec <= 600):
        parser.error('require 0 <= --start-sec < --end-sec <= 600')
    run(args)


if __name__ == '__main__':
    main()
