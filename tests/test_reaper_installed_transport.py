"""Offline adapter round-trip through the pinned controller file-drop client."""
from __future__ import annotations

import importlib
import io
import json
import subprocess
import sys
import tarfile
import threading
from pathlib import Path

import pytest

from llm_studio.reaper import ReaperStudioAdapter, Session, Track


CONTROLLER = Path(__file__).resolve().parents[2] / 'reaper-controller'
PIN = Path(__file__).resolve().parents[1] / 'adapters/reaper/controller-pin.json'
PINNED_COMMIT = 'fd56d0008ffa5fba25cc58a70e5ae632c80b4c16'


def test_replace_stem_round_trips_through_pinned_file_drop_client(tmp_path, monkeypatch):
    if not (CONTROLLER / 'src/reaper_connector/bridge.py').is_file():
        pytest.skip('pinned reaper-controller checkout is unavailable')
    pin = json.loads(PIN.read_text())
    assert pin['commit'] == PINNED_COMMIT
    archive = subprocess.run(
        ['git', '-C', str(CONTROLLER), 'archive', '--format=tar',
         PINNED_COMMIT, 'src/reaper_connector'], check=True,
        capture_output=True,
    ).stdout
    source_root = tmp_path / 'pinned-controller'
    source_root.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:') as bundle:
        bundle.extractall(source_root)

    for module in ('reaper_connector.bridge', 'reaper_connector.doctor',
                   'reaper_connector'):
        monkeypatch.delitem(sys.modules, module, raising=False)
    monkeypatch.syspath_prepend(str(source_root / 'src'))
    bridge = importlib.import_module('reaper_connector.bridge')
    assert Path(bridge.__file__).is_relative_to(source_root)

    resource = tmp_path / 'profile'
    bridge_dirs = bridge.bridge_dirs(resource)
    for directory in bridge_dirs.values():
        directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('REAPER_RESOURCE_PATH', str(resource))

    project = tmp_path / 'session.RPP'
    project.write_text('disposable project fixture')
    session = Session(str(project), 'epoch:1', project, 5,
                      (Track('{track}', 'Bass', 0),))
    old_path = '/disposable/old.wav'
    baseline = {'track_guid': '{track}', 'item_guid': '{item}',
                'take_guid': '{take}', 'source_path': old_path,
                'source_type': 'WAVE', 'position_sec': 1.25,
                'length_sec': 2, 'channels': 1, 'sample_rate': 48000,
                'state_change_count': 5}
    stem = tmp_path / 'replacement.wav'
    stem.write_bytes(b'offline WAV payload fixture')
    observed_request: dict = {}
    stop = threading.Event()

    def daemon():
        incoming, outgoing = bridge_dirs['in'], bridge_dirs['out']
        while not stop.is_set():
            for request_path in incoming.glob('*.json'):
                try:
                    request = json.loads(request_path.read_text())
                except (OSError, ValueError):
                    continue
                if request['op'] != 'studio.replace_stem':
                    continue
                observed_request.update(request)
                payload = request['params']
                result = {'observed': {**baseline,
                    'source_path': payload['stem_path'],
                    'state_change_count': 6}, 'old_source_path': old_path}
                reply_path = outgoing / f"{request['op_id']}.json"
                temporary = reply_path.with_suffix('.json.tmp')
                temporary.write_text(json.dumps({'v': 1,
                    'op_id': request['op_id'], 'ok': True, 'result': result,
                    'adapter': 'reascript-lua', 'evidence': []}))
                temporary.rename(reply_path)
            stop.wait(.01)

    worker = threading.Thread(target=daemon, daemon=True)
    worker.start()
    adapter = ReaperStudioAdapter(
        lambda op, params: bridge.send(op, params, timeout=2,
                                       resource_path=resource),
        disposable_roots=(tmp_path,),
    )
    try:
        result = adapter.replace_stem(session, '{track}', baseline, stem)
    finally:
        stop.set()
        worker.join(timeout=1)

    assert observed_request['v'] == bridge.PROTOCOL_V
    assert observed_request['op'] == 'studio.replace_stem'
    assert observed_request['params']['session_id'] == session.id
    assert observed_request['params']['session_token'] == session.token
    assert observed_request['params']['track_guid'] == '{track}'
    assert observed_request['params']['item_guid'] == '{item}'
    assert observed_request['params']['expected'] == baseline
    staged = Path(observed_request['params']['stem_path'])
    assert staged.is_file()
    assert staged.read_bytes() == stem.read_bytes()
    assert result['observed']['source_path'] == str(staged)
