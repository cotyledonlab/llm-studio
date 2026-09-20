"""Contract and failure-path tests; real REAPER evidence remains mandatory."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pytest

from llm_studio.reaper import ReaperAdapterError, ReaperStudioAdapter, Session, Track


def test_native_handler_contract(tmp_path):
    lua = shutil.which('lua')
    if not lua:
        pytest.skip('Lua required for handler contract')
    # The handler itself enforces its canonical disposable root.
    root = Path('/private/tmp/llm-studio-reaper')
    root.mkdir(exist_ok=True, parents=True)
    subprocess.run([lua, str(Path(__file__).parent / 'fixtures/reaper_automation.lua'),
                    str(root / 'contract.RPP'), 'adapters/reaper/studio_handler.lua'], check=True)


def baseline():
    return dict(track_guid='{track}', envelope_guid='{env}', fingerprint='observation',
                start_sec=1, end_sec=3, time_domain='project_seconds', scaling_mode=1,
                project_timebase=0, track_timebase=-1, effective_timebase=0,
                attachment_domain='project_time',
                state_change_count=1, observed_at=5, max_age_sec=30,
                points=[dict(time_sec=t, quarter_note=t * 2, volume=v, raw_value=v,
                             shape=0, tension=0, selected=False)
                        for t, v in [(1, 1), (2, .5), (3, 1)]])


def test_db_patch_and_readback_validation(tmp_path):
    project = tmp_path / 'session.RPP'
    project.touch()
    session = Session(str(project), 'token', project, 1, (Track('{track}', 'Keys', 0),))
    sent = []
    def send(op, params):
        sent.append((op, params))
        return {'ok': True, 'result': {'observed': baseline(), 'receipt': 'receipt'}}
    adapter = ReaperStudioAdapter(send, disposable_roots=(tmp_path,))
    points = [dict(time_sec=t, gain_db=g) for t, g in [(1, 0), (2, -6.020599913279624), (3, 0)]]
    result = adapter.patch_volume_envelope(session, '{track}', baseline(), points)
    assert sent[-1][1]['points'][1]['volume'] == pytest.approx(.5)
    assert result['observed']['points'][1]['gain_db'] == pytest.approx(-6.020599913)
    points[1]['gain_db'] = -12
    with pytest.raises(ReaperAdapterError, match='readback differs'):
        adapter.patch_volume_envelope(session, '{track}', baseline(), points)


@pytest.mark.parametrize('field,value', [('fingerprint', ''), ('state_change_count', None),
    ('scaling_mode', 4), ('max_age_sec', 1000), ('effective_timebase', 1),
    ('attachment_domain', 'project_beats')])
def test_invalid_observation(field, value):
    data = baseline()
    data[field] = value
    with pytest.raises(ReaperAdapterError):
        ReaperStudioAdapter._envelope_observed(data, '{track}', 1, 3)


def test_prepares_bounded_timebase_wrapper():
    base = Path('/private/tmp/llm-studio-reaper')
    base.mkdir(exist_ok=True, parents=True)
    with tempfile.TemporaryDirectory(prefix='test-timebase-', dir=base) as name:
        source = Path(name) / 'source.RPP'
        profile = Path(name) / 'profile'
        source.write_text('<REAPER_PROJECT 0.1\n>\n')
        profile.mkdir()
        cfgfile = profile / 'reaper.ini'
        cfgfile.write_text('[REAPER]\n')
        result = subprocess.run(
            [sys.executable, 'tools/qualification/reaper_automation_timebase.py',
             '--source', str(source), '--cfgfile', str(cfgfile)],
            check=True, text=True, capture_output=True,
        )
        root = Path(result.stdout.strip())
        assert root.is_dir()
        text = (root / 'project_time_inherited.lua').read_text()
        assert 'STUDIO_AUTOMATION_TIMEBASE' in text
        assert str(source) in text
        assert 'reaper_automation_timebase.lua' in text
        shutil.rmtree(root)
