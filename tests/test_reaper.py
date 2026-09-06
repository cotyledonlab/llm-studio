from dataclasses import replace
from pathlib import Path

import pytest

from llm_studio.reaper import (
    ReaperAdapterError, ReaperStudioAdapter, Session, SessionChanged,
    Track, TrackBindingOrphaned, UnsupportedReaperCapability,
)


@pytest.fixture
def session(tmp_path):
    project = tmp_path / 'session.RPP'
    project.write_text('disposable test fixture')
    return Session(str(project), 'epoch:1', project, 5, (Track('{a}', 'Bass', 0), Track('{b}', 'Keys', 1)))


def test_snapshot_and_reads_keep_native_guid_after_rename_reorder(session):
    calls = []
    def send(op, params):
        calls.append((op, params))
        if op == 'studio.session_snapshot':
            return {'ok': True, 'result': {'session': {'id': session.id, 'path': str(session.path), 'token': session.token, 'state_change_count': 7},
                'tracks': [{'guid': '{b}', 'name': 'Renamed', 'index': 0}, {'guid': '{a}', 'name': 'Bass', 'index': 1}]}}
        return {'ok': True, 'result': {'guid': '{b}', 'volume': .5, 'pan': -.3, 'fx': {}}}
    adapter = ReaperStudioAdapter(send)
    current = adapter.observe_session()
    assert current.track('{b}').index == 0
    assert current.track('{b}').name == 'Renamed'
    observed = adapter.read_track(current, '{b}')
    assert observed['gain_db'] == pytest.approx(-6.020599913)
    assert observed['fx'] == []
    assert 'track' not in calls[-1][1]
    assert calls[-1][1]['track_guid'] == '{b}'


@pytest.mark.parametrize('raised', [False, True])
@pytest.mark.parametrize('code,kind', [('SESSION_CHANGED', SessionChanged), ('TRACK_ORPHANED', TrackBindingOrphaned), ('UNKNOWN_OP', UnsupportedReaperCapability)])
def test_controller_reply_and_exception_errors_preserve_type(session, raised, code, kind):
    class ControllerError(Exception):
        pass
    def send(op, params):
        if raised:
            error = ControllerError('observed failure')
            error.code = code
            raise error
        return {'ok': False, 'error': {'code': code}}
    with pytest.raises(kind):
        ReaperStudioAdapter(send).read_track(session, '{a}')


def test_mixer_db_and_explicit_silence_require_real_readback(session):
    requests = []
    def send(op, params):
        requests.append(params)
        return {'ok': True, 'result': {'observed': {'volume': params['volume'], 'pan': params.get('pan', 0)}}}
    adapter = ReaperStudioAdapter(send, disposable_roots=(session.path.parent,))
    adapter.set_mixer(session, '{a}', gain_db=-6.020599913279624, pan=-.5)
    assert requests[-1]['volume'] == pytest.approx(.5)
    adapter.set_mixer(session, '{a}', silent=True)
    assert requests[-1]['volume'] == 0
    adapter._bridge_send = lambda *args: {'ok': True, 'result': {'observed': {'volume': .7}}}
    with pytest.raises(ReaperAdapterError, match='readback differs'):
        adapter.set_mixer(session, '{a}', gain_db=0)


@pytest.mark.parametrize('params', [{'gain_db': float('nan')}, {'pan': 2}, {'silent': True, 'gain_db': 0}, {'pan': True}])
def test_invalid_mixer_never_dispatches(session, params):
    adapter = ReaperStudioAdapter(lambda *args: pytest.fail('unexpected dispatch'))
    with pytest.raises(ValueError):
        adapter.set_mixer(session, '{a}', **params)


@pytest.mark.parametrize('reply', [{}, {'result': {}}, {'ok': True, 'result': {}}, {'ok': True, 'result': {'guid': '{other}', 'volume': 1, 'pan': 0, 'fx': []}}])
def test_incomplete_observation_rejected(session, reply):
    with pytest.raises(ReaperAdapterError):
        ReaperStudioAdapter(lambda *args: reply).read_track(session, '{a}')


def test_import_stages_immutable_copy_and_validates_actual_item(session, tmp_path):
    stem = tmp_path / 'render.wav'
    stem.write_bytes(b'unit test source bytes; actual WAV decoding is qualified in REAPER')
    def send(op, params):
        return {'ok': True, 'result': {'durable_path': params['stem_path'], 'track_guid': '{a}', 'item_guid': '{item}', 'length_sec': 1, 'position_sec': params['position_sec']}}
    adapter = ReaperStudioAdapter(send, disposable_roots=(tmp_path,))
    result = adapter.import_stem(session, '{a}', stem, position_sec=2)
    copied = Path(result['durable_path'])
    original = copied.read_bytes()
    stem.write_bytes(b'changed source')
    assert copied.read_bytes() == original
    adapter._bridge_send = lambda *args: {'ok': True, 'result': {'durable_path': '/wrong.wav'}}
    with pytest.raises(ReaperAdapterError, match='media readback'):
        adapter.import_stem(session, '{a}', stem)


def test_import_rejects_media_symlink_and_producer_project(session, tmp_path):
    source = tmp_path / 'source.wav'
    source.write_bytes(b'fixture')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (tmp_path / 'media').symlink_to(outside)
    adapter = ReaperStudioAdapter(lambda *args: pytest.fail('unexpected dispatch'), disposable_roots=(tmp_path,))
    with pytest.raises(ReaperAdapterError, match='symlink'):
        adapter.import_stem(session, '{a}', source)
    with pytest.raises(ReaperAdapterError, match='outside disposable'):
        ReaperStudioAdapter(lambda *args: None, disposable_roots=()).set_mixer(session, '{a}', gain_db=0)
