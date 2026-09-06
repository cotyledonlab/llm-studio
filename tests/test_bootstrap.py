from __future__ import annotations

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


def test_partial_apply_has_recoverable_receipt(tmp_path, monkeypatch):
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
    monkeypatch.setattr(bootstrap.os, 'replace', real_replace)
    rollback(receipt, running=lambda: False)
    assert not (resource / 'Scripts/agent_bridge.lua').exists()
    assert not (resource / 'reaper.ini').exists()


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


def test_broken_symlink_never_written(tmp_path, monkeypatch):
    root = controller(tmp_path)
    pin(monkeypatch, root)
    resource = tmp_path / 'resource'
    (resource / 'Scripts').mkdir(parents=True)
    (resource / 'Scripts/agent_bridge.lua').symlink_to(tmp_path / 'missing')
    with pytest.raises(UnsafeBootstrap, match='symlink'):
        plan_bootstrap(resource, root, tmp_path / 'no-extension')
