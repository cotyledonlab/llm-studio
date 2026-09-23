from __future__ import annotations

import json
import os
import shutil
import shlex
import subprocess
from pathlib import Path

import pytest

from llm_studio.bootstrap import (
    PINNED_CONTROLLER_COMMIT,
    BootstrapError,
    RollbackRefused,
    UnsafeBootstrap,
    apply,
    dry_run,
    plan_bootstrap,
    rollback,
    save_plan,
    load_plan,
    save_result,
    load_result,
    verify,
    load_recovery_result,
)


def controller(tmp_path: Path) -> Path:
    root = tmp_path / "controller"
    (root / "bridge").mkdir(parents=True)
    (root / "osc").mkdir()
    (root / "bridge/agent_bridge.lua").write_text("-- pinned bridge\nfunction x() end\n")
    (root / "osc/Agent.ReaperOSC").write_text("TRACK_VOLUME n/track/@/volume\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-qm", "fixture"], check=True)
    return root


def pin(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr("llm_studio.bootstrap.PINNED_CONTROLLER_COMMIT", subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip())


def test_dry_run_is_side_effect_free_and_preserves_ini(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = controller(tmp_path)
    pin(monkeypatch, root)
    resource = tmp_path / "resource"
    resource.mkdir()
    (resource / "reaper.ini").write_text("foo=keep\ncsurf_cnt=1\n")
    plan = plan_bootstrap(resource, root, tmp_path / "missing-project")
    report = dry_run(plan)
    assert report["mode"] == "dry-run"
    assert (resource / "reaper.ini").read_text() == "foo=keep\ncsurf_cnt=1\n"
    ini = next(f for f in plan.files if f.relative_path == "reaper.ini")
    assert b"foo=keep" in ini.content and b'"Agent"' in ini.content


def test_apply_verify_rollback_and_idempotence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = controller(tmp_path)
    pin(monkeypatch, root)
    resource = tmp_path / "resource"
    resource.mkdir()
    (resource / "reaper.ini").write_text("foo=keep\n")
    (resource / "Scripts").mkdir()
    old_bridge = resource / "Scripts/agent_bridge.lua"
    old_bridge.write_text("old bridge\n")
    plan = plan_bootstrap(resource, root, tmp_path / "no-extension")
    result = apply(plan, running=lambda: False)
    assert verify(result)["ok"]
    assert old_bridge.read_text() == "-- pinned bridge\nfunction x() end\n"
    assert (resource / "reaper.ini").read_text().startswith("foo=keep")
    assert rollback(result, running=lambda: False) == ("Scripts/agent_bridge.lua", "OSC/Agent.ReaperOSC", "reaper.ini")
    assert old_bridge.read_text() == "old bridge\n"
    again = plan_bootstrap(resource, root, tmp_path / "no-extension")
    second = apply(again, running=lambda: False)
    assert apply(plan_bootstrap(resource, root, tmp_path / "no-extension"), running=lambda: False).changed == ()
    assert verify(second)["ok"]


def test_refuses_running_reaper_stale_plan_symlink_and_post_apply_edits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = controller(tmp_path)
    pin(monkeypatch, root)
    resource = tmp_path / "resource"
    resource.mkdir()
    plan = plan_bootstrap(resource, root, tmp_path / "no-extension")
    with pytest.raises(UnsafeBootstrap, match="running"):
        apply(plan, running=lambda: True)
    (resource / "Scripts").mkdir()
    (resource / "Scripts/agent_bridge.lua").write_text("external edit")
    with pytest.raises(BootstrapError, match="changed since plan"):
        apply(plan, running=lambda: False)
    escaped = tmp_path / "escaped"
    escaped.mkdir()
    (resource / "OSC").symlink_to(escaped, target_is_directory=True)
    with pytest.raises(UnsafeBootstrap, match="symlink"):
        plan_bootstrap(resource, root, tmp_path / "no-extension")

    # A fresh resource proves rollback never overwrites a post-apply change.
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    result = apply(plan_bootstrap(fresh, root, tmp_path / "no-extension"), running=lambda: False)
    (fresh / "Scripts/agent_bridge.lua").write_text("producer edit")
    with pytest.raises(RollbackRefused, match="post-apply"):
        rollback(result, running=lambda: False)


def test_rejects_unapproved_agent_config_and_persists_reviewed_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = controller(tmp_path)
    pin(monkeypatch, root)
    resource = tmp_path / "resource"
    resource.mkdir()
    (resource / "reaper.ini").write_text('[REAPER]\ncsurf_0=OSC "Agent" 3 8000 "0.0.0.0" 9000 1024 10 "Agent"\n')
    with pytest.raises(BootstrapError, match="differs"):
        plan_bootstrap(resource, root, tmp_path / "no-extension")

    (resource / "reaper.ini").write_text("[REAPER]\nfoo=keep\n")
    plan = plan_bootstrap(resource, root, tmp_path / "no-extension")
    plan_file = tmp_path / "reviewed-plan.json"
    save_plan(plan, plan_file)
    assert load_plan(plan_file) == plan
    result = apply(plan, running=lambda: False)
    result_file = tmp_path / "apply-result.json"
    save_result(result, result_file)
    assert load_result(result_file).changed == result.changed


@pytest.mark.parametrize('stage_changed', [False, True])
def test_partial_apply_has_recoverable_receipt(tmp_path, monkeypatch, stage_changed):
    import llm_studio.bootstrap as bootstrap
    root = controller(tmp_path)
    pin(monkeypatch, root)
    resource = tmp_path / 'resource'
    resource.mkdir()
    plan = plan_bootstrap(resource, root, tmp_path / 'no-extension')
    real_replace = bootstrap.os.replace
    def fail_second(source, target):
        if str(target).endswith('OSC/Agent.ReaperOSC'):
            raise OSError('injected disk error')
        return real_replace(source, target)
    monkeypatch.setattr(bootstrap.os, 'replace', fail_second)
    with pytest.raises(OSError, match='injected'):
        apply(plan, running=lambda: False)
    backup = next((resource / 'LLMStudioBackups').iterdir())
    receipt = load_recovery_result(backup)
    records = json.loads((backup / 'manifest.json').read_text())['files']
    staged = resource / records[1]['temporary']
    assert not staged.exists()  # Synchronous replacement failure cleaned its file.
    content = next(item.content for item in plan.files if item.relative_path == records[1]['path'])
    # Simulate a completed stage left by interruption, or a subsequent edit.
    staged.write_bytes(b'changed after interruption' if stage_changed else content)
    unrelated = resource / 'OSC/.other-transaction-new'
    unrelated.write_bytes(b'leave me')
    monkeypatch.setattr(bootstrap.os, 'replace', real_replace)
    rollback(receipt, running=lambda: False)
    assert not (resource / 'Scripts/agent_bridge.lua').exists()
    assert not (resource / 'reaper.ini').exists()
    if stage_changed:
        assert staged.read_bytes() == b'changed after interruption'
    else:
        assert not staged.exists()
    assert unrelated.read_bytes() == b'leave me'
    assert apply(plan_bootstrap(resource, root, tmp_path / 'no-extension'), running=lambda: False).changed


def test_rollback_replace_failure_can_be_retried(tmp_path, monkeypatch):
    import llm_studio.bootstrap as bootstrap
    root = controller(tmp_path)
    pin(monkeypatch, root)
    resource = tmp_path / 'resource'
    resource.mkdir()
    (resource / 'Scripts').mkdir()
    (resource / 'Scripts/agent_bridge.lua').write_text('old bridge')
    result = apply(plan_bootstrap(resource, root, tmp_path / 'no-extension'), running=lambda: False)
    real_replace = bootstrap.os.replace
    def fail_first(source, target):
        if str(target).endswith('Scripts/agent_bridge.lua'):
            raise OSError('injected rollback disk error')
        return real_replace(source, target)
    monkeypatch.setattr(bootstrap.os, 'replace', fail_first)
    with pytest.raises(OSError, match='rollback disk error'):
        rollback(result, running=lambda: False)
    monkeypatch.setattr(bootstrap.os, 'replace', real_replace)
    assert rollback(result, running=lambda: False) == (
        'Scripts/agent_bridge.lua', 'OSC/Agent.ReaperOSC', 'reaper.ini')
    assert (resource / 'Scripts/agent_bridge.lua').read_text() == 'old bridge'


def test_corrupt_later_backup_prevents_any_rollback(tmp_path, monkeypatch):
    root = controller(tmp_path)
    pin(monkeypatch, root)
    resource = tmp_path / 'resource'
    (resource / 'Scripts').mkdir(parents=True)
    (resource / 'Scripts/agent_bridge.lua').write_text('old script')
    (resource / 'reaper.ini').write_text('[REAPER]\nfoo=keep\n')
    result = apply(plan_bootstrap(resource, root, tmp_path / 'no-extension'), running=lambda: False)
    installed = (resource / 'Scripts/agent_bridge.lua').read_bytes()
    (result.backup_dir / 'reaper.ini').write_text('corrupted backup')
    with pytest.raises(RollbackRefused, match='integrity'):
        rollback(result, running=lambda: False)
    assert (resource / 'Scripts/agent_bridge.lua').read_bytes() == installed


def test_ini_section_and_unknown_process_status():
    import llm_studio.bootstrap as bootstrap
    original = b'[REAPER]\nfoo=keep\n[Other]\ncsurf_cnt=50\n'
    updated = bootstrap._agent_ini(original)
    assert updated.endswith(b'[Other]\ncsurf_cnt=50\n')
    assert b'csurf_cnt=1\n[Other]' in updated
    existing = ('[reaper]\ncsurf_0=' + bootstrap.OSC_AGENT_LINE + '\ncsurf_cnt=1\n[Other]\n').encode()
    assert bootstrap._agent_ini(existing) == existing


def test_studio_hook_reserves_bridge_heartbeat_before_starting_deferred_loop():
    """The startup claim precedes setup and the daemon callback checks its owner."""
    import re
    import llm_studio.bootstrap as bootstrap

    patch_text = (Path(__file__).parents[1] / 'adapters/reaper/controller-studio-hook.patch').read_text()
    match = re.search(r'(?ms)^@@ -185,1 \+185,5 @@\n(.*?)(?=^@@ |\Z)', patch_text)
    assert match, 'studio hook must patch the pinned heartbeat guard'
    hunk = ('@@ -185,1 +185,5 @@\n' + match.group(1)).encode()
    original = ('\n' * 184
                + "if os.time() - last_ext < 15 then return end\n\n"
                + 'local function read_file(p) end\n'
                + 'reaper.defer(tick)\n').encode()

    installed = bootstrap._apply_unified_patch(original, hunk).decode()
    stale_check = installed.index("if os.time() - last_ext < 15 then return end")
    owner_claim = installed.index("reaper.SetExtState('agent_bridge', 'owner', owner_token, false)")
    reservation = installed.index("reaper.SetExtState('agent_bridge', 'heartbeat', tostring(os.time()), false)")
    next_definition = installed.index('local function read_file(p)')
    deferred_loop = installed.index('reaper.defer(tick)')
    assert stale_check < owner_claim < reservation < next_definition < deferred_loop
    assert "if reaper.GetExtState('agent_bridge', 'owner') ~= owner_token then return end" in patch_text


@pytest.mark.skipif(
    not os.environ.get('REAPER_CONTROLLER_CHECKOUT') or not shutil.which('lua'),
    reason='set REAPER_CONTROLLER_CHECKOUT and install Lua for the mocked daemon test',
)
def test_stalled_daemon_cannot_scan_after_stale_owner_takeover(tmp_path):
    """A replacement generation makes a delayed callback inert before queue scan."""
    from llm_studio.bootstrap import _apply_unified_patch

    controller_path = Path(os.environ['REAPER_CONTROLLER_CHECKOUT'])
    base_bridge = (controller_path / 'bridge/agent_bridge.lua').read_bytes()
    hook = (Path(__file__).parents[1] / 'adapters/reaper/controller-studio-hook.patch').read_bytes()
    installed = tmp_path / 'agent_bridge.lua'
    installed.write_bytes(_apply_unified_patch(base_bridge, hook))
    resource = tmp_path / 'resource'
    (resource / 'AgentBridge/log').mkdir(parents=True)
    harness = tmp_path / 'mock_reaper.lua'
    harness.write_text(f'''\
local states, callbacks, guid, scans = {{}}, {{}}, 0, 0
local resource = {json.dumps(str(resource))}
reaper = {{
  GetResourcePath = function() return resource end,
  RecursiveCreateDirectory = function() return 1 end,
  GetExtState = function(_, key) return states[key] or '' end,
  SetExtState = function(_, key, value) states[key] = value end,
  genGuid = function() guid = guid + 1; return 'generation-' .. guid end,
  defer = function(fn) callbacks[#callbacks + 1] = fn end,
  time_precise = function() return 1 end,
  EnumerateFiles = function() scans = scans + 1; return nil end,
}}
local script = {json.dumps(str(installed))}
dofile(script)
assert(#callbacks == 1)
local old_owner = states.owner
states.heartbeat = tostring(os.time() - 16)
dofile(script)
assert(#callbacks == 2 and states.owner ~= old_owner)
callbacks[1]()
assert(scans == 0, 'stalled generation scanned after takeover')
callbacks[2]()
assert(scans == 1, 'current generation did not scan')
local claimed_owner = states.owner
dofile(script)
assert(states.owner == claimed_owner, 'fresh sibling unexpectedly claimed ownership')
assert(#callbacks == 3)
''')
    subprocess.run([shutil.which('lua'), str(harness)], check=True, capture_output=True, text=True)


def test_broken_symlink_never_written(tmp_path, monkeypatch):
    root = controller(tmp_path)
    pin(monkeypatch, root)
    resource = tmp_path / 'resource'
    (resource / 'Scripts').mkdir(parents=True)
    (resource / 'Scripts/agent_bridge.lua').symlink_to(tmp_path / 'missing')
    with pytest.raises(UnsafeBootstrap, match='symlink'):
        plan_bootstrap(resource, root, tmp_path / 'no-extension')


def test_isolated_empty_profile_process_guard_matching_unrelated_and_unknown(tmp_path, monkeypatch):
    import llm_studio.bootstrap as bootstrap
    resource = tmp_path / 'new-resource'
    resource.mkdir()
    monkeypatch.setattr(bootstrap, 'ISOLATED_PROFILE_ROOT', tmp_path)
    expected = str(resource / 'reaper.ini')

    def probe_for(pgrep_result, ps_result):
        results = iter((pgrep_result, ps_result))
        calls = []
        def run(*args, **kwargs):
            calls.append(args[0])
            return next(results)
        monkeypatch.setattr(bootstrap.subprocess, 'run', run)
        return calls

    calls = probe_for(subprocess.CompletedProcess([], 0, '123\n', ''),
                      subprocess.CompletedProcess([], 0, f'123 /Applications/REAPER.app/Contents/MacOS/REAPER -cfgfile {expected} project.RPP\n', ''))
    assert bootstrap.isolated_profile_running(resource)
    assert calls[1] == ['ps', '-ww', '-axo', 'pid=,command=']

    probe_for(subprocess.CompletedProcess([], 0, '123\n', ''),
              subprocess.CompletedProcess([], 0, '123 /Applications/REAPER.app/Contents/MacOS/REAPER -cfgfile /tmp/other/reaper.ini project.RPP\n', ''))
    assert not bootstrap.isolated_profile_running(resource)

    probe_for(subprocess.CompletedProcess([], 3, '', 'permission denied'),
              subprocess.CompletedProcess([], 0, '', ''))
    with pytest.raises(UnsafeBootstrap, match='probe returned status 3'):
        bootstrap.isolated_profile_running(resource)


@pytest.mark.parametrize('command, message', [
    ('/Applications/REAPER.app/Contents/MacOS/REAPER project.RPP', 'exactly one'),
    ('/Applications/REAPER.app/Contents/MacOS/REAPER -cfgfile /tmp/a.ini -cfgfile /tmp/b.ini', 'exactly one'),
    ('/Applications/REAPER.app/Contents/MacOS/REAPER -cfgfile relative.ini', 'relative'),
    ('/Applications/REAPER.app/Contents/MacOS/REAPER -cfgfile', 'incomplete'),
    ('/Applications/REAPER.app/Contents/MacOS/REAPER -cfgfile=', 'incomplete'),
    ('/Applications/REAPER.app/Contents/MacOS/REAPER "-cfgfile /tmp/a.ini', 'malformed argv'),
])
def test_isolated_process_guard_rejects_unrecognized_reaper_argv(tmp_path, monkeypatch, command, message):
    import llm_studio.bootstrap as bootstrap
    resource = tmp_path / 'new-resource'
    resource.mkdir()
    monkeypatch.setattr(bootstrap, 'ISOLATED_PROFILE_ROOT', tmp_path)
    results = iter((
        subprocess.CompletedProcess([], 0, '123\n', ''),
        subprocess.CompletedProcess([], 0, f'123 {command}\n', ''),
    ))
    monkeypatch.setattr(bootstrap.subprocess, 'run', lambda *a, **k: next(results))
    with pytest.raises(UnsafeBootstrap, match=message):
        bootstrap.isolated_profile_running(resource)


def test_isolated_apply_accepts_distinct_profile_and_saves_receipt(tmp_path, monkeypatch):
    import llm_studio.bootstrap as bootstrap
    root = controller(tmp_path)
    pin(monkeypatch, root)
    allowed = tmp_path / 'allowed'
    allowed.mkdir()
    monkeypatch.setattr(bootstrap, 'ISOLATED_PROFILE_ROOT', allowed)
    resource = allowed / 'new-resource'
    resource.mkdir()
    plan = plan_bootstrap(resource, root, tmp_path / 'no-extension')
    argv = '/Applications/REAPER.app/Contents/MacOS/REAPER -cfgfile /private/tmp/llm-studio-reaper/a3-probe/profile/reaper.ini project.RPP'
    results = iter((
        subprocess.CompletedProcess([], 0, '123\n', ''),
        subprocess.CompletedProcess([], 0, f'123 {argv}\n', ''),
    ))
    real_run = bootstrap.subprocess.run
    def run_probe(args, **kwargs):
        return next(results) if args[0] in {'pgrep', 'ps'} else real_run(args, **kwargs)
    monkeypatch.setattr(bootstrap.subprocess, 'run', run_probe)

    result = apply(plan, isolated_empty_profile=True)
    receipt = tmp_path / 'isolated-receipt.json'
    save_result(result, receipt)
    assert verify(load_result(receipt))['ok']
    assert set(result.changed) == {item.relative_path for item in plan.files}
    assert receipt.is_file()


def test_isolated_apply_refuses_exact_profile_before_target_writes(tmp_path, monkeypatch):
    import llm_studio.bootstrap as bootstrap
    root = controller(tmp_path)
    pin(monkeypatch, root)
    allowed = tmp_path / 'allowed'
    allowed.mkdir()
    monkeypatch.setattr(bootstrap, 'ISOLATED_PROFILE_ROOT', allowed)
    resource = allowed / 'new-resource'
    resource.mkdir()
    plan = plan_bootstrap(resource, root, tmp_path / 'no-extension')
    cfg = shlex.quote(str(resource / 'reaper.ini'))
    results = iter((
        subprocess.CompletedProcess([], 0, '123\n', ''),
        subprocess.CompletedProcess([], 0, f'123 /Applications/REAPER.app/Contents/MacOS/REAPER -cfgfile {cfg} project.RPP\n', ''),
    ))
    real_run = bootstrap.subprocess.run
    def run_probe(args, **kwargs):
        return next(results) if args[0] in {'pgrep', 'ps'} else real_run(args, **kwargs)
    monkeypatch.setattr(bootstrap.subprocess, 'run', run_probe)
    with pytest.raises(UnsafeBootstrap, match='using the isolated profile'):
        apply(plan, isolated_empty_profile=True)
    assert list(resource.iterdir()) == []


def test_isolated_apply_refuses_nonempty_and_symlinked_resource(tmp_path, monkeypatch):
    import llm_studio.bootstrap as bootstrap
    root = controller(tmp_path)
    pin(monkeypatch, root)
    allowed = tmp_path / 'allowed'
    allowed.mkdir()
    monkeypatch.setattr(bootstrap, 'ISOLATED_PROFILE_ROOT', allowed)
    resource = allowed / 'empty-resource'
    resource.mkdir()
    plan = plan_bootstrap(resource, root, tmp_path / 'no-extension')
    (resource / 'unexpected').write_text('leave intact')
    with pytest.raises(UnsafeBootstrap, match='must be empty'):
        apply(plan, isolated_empty_profile=True)
    assert (resource / 'unexpected').read_text() == 'leave intact'

    (resource / 'unexpected').unlink()
    actual_parent = allowed / 'actual-parent'
    actual_parent.mkdir()
    (actual_parent / 'empty-resource').mkdir()
    link_parent = allowed / 'linked-parent'
    link_parent.symlink_to(actual_parent, target_is_directory=True)
    linked = link_parent / 'empty-resource'
    linked_plan = plan_bootstrap(linked, root, tmp_path / 'no-extension')
    with pytest.raises(UnsafeBootstrap, match='contains symlink'):
        apply(linked_plan, isolated_empty_profile=True)
