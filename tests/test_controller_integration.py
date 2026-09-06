"""Opt-in test of actual pinned controller resources; never touches a live profile."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from llm_studio.bootstrap import apply, plan_bootstrap, rollback, verify


@pytest.mark.skipif(not os.environ.get('REAPER_CONTROLLER_CHECKOUT'), reason='set REAPER_CONTROLLER_CHECKOUT for real pinned source qualification')
def test_real_pinned_resource_install_and_rollback(tmp_path):
    controller = Path(os.environ['REAPER_CONTROLLER_CHECKOUT'])
    resource = tmp_path / 'never-launched-profile'
    resource.mkdir()
    original = b'[reaper]\ncustompref=preserved\n[Other]\ncsurf_cnt=12\n'
    (resource / 'reaper.ini').write_bytes(original)
    plan = plan_bootstrap(resource, controller)
    # This newly-created resource directory has never been given to REAPER.
    result = apply(plan, running=lambda: False)
    assert verify(result)['ok']
    assert b'custompref=preserved' in (resource / 'reaper.ini').read_bytes()
    if shutil.which('luac'):
        for script in ('agent_bridge.lua', 'llm_studio_reaper.lua'):
            subprocess.run(['luac', '-p', str(resource / 'Scripts' / script)], check=True)
    assert apply(plan_bootstrap(resource, controller), running=lambda: False).changed == ()
    rollback(result, running=lambda: False)
    assert (resource / 'reaper.ini').read_bytes() == original
    assert not (resource / 'Scripts/agent_bridge.lua').exists()
