import argparse
import json
import sys
import types
from pathlib import Path

import pytest

from tools.qualification import reaper_adapter_probe as probe


def args(tmp_path, **extra):
    values = dict(controller=tmp_path, resource=tmp_path, output=tmp_path / "evidence.json",
                  timeout=1.0, manual_fader=False)
    values.update(extra)
    return argparse.Namespace(**values)


def setup_probe(monkeypatch, snapshot):
    monkeypatch.setattr(probe.bootstrap, "validate_controller_checkout", lambda _: "fd56d")
    monkeypatch.setattr(probe, "_source_check", lambda _: {"expected_source": "x", "imported_source": "x/y"})
    monkeypatch.setattr(probe, "_snapshot", snapshot)
    bridge = types.SimpleNamespace(send=lambda *args, **kwargs: pytest.fail("unexpected bridge call"))
    doctor = types.SimpleNamespace(default_resource_path=lambda: Path("/fake/resource"))
    package = types.ModuleType("reaper_connector")
    package.__path__ = []
    package.bridge = bridge
    doctor_module = types.ModuleType("reaper_connector.doctor")
    doctor_module.default_resource_path = doctor.default_resource_path
    monkeypatch.setitem(sys.modules, "reaper_connector", package)
    monkeypatch.setitem(sys.modules, "reaper_connector.bridge", bridge)
    monkeypatch.setitem(sys.modules, "reaper_connector.doctor", doctor_module)


def test_default_is_one_noninteractive_snapshot(tmp_path, monkeypatch):
    calls = []
    setup_probe(monkeypatch, lambda _: calls.append(1) or {"session": {"id": "p", "token": "t"}, "tracks": [], "fx_nonempty": False})
    evidence = probe.run(args(tmp_path))
    assert len(calls) == 1
    assert evidence["manual_fader"] is None
    assert evidence["snapshot"]["session"]["id"] == "p"
    assert json.loads((tmp_path / "evidence.json").read_text())["ok"] is True


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_timeout_must_be_finite_and_positive(tmp_path, timeout):
    with pytest.raises(ValueError, match="finite and positive"):
        probe.run(args(tmp_path, timeout=timeout))


def test_existing_output_and_symlink_are_refused(tmp_path, monkeypatch):
    existing = tmp_path / "existing.json"
    existing.write_text("keep")
    with pytest.raises(FileExistsError):
        probe.run(args(tmp_path, output=existing))
    link = tmp_path / "link.json"
    link.symlink_to(existing)
    with pytest.raises(FileExistsError):
        probe.run(args(tmp_path, output=link))
    dangling = tmp_path / "dangling.json"
    dangling.symlink_to(tmp_path / "missing.json")
    with pytest.raises(FileExistsError):
        probe.run(args(tmp_path, output=dangling))


def test_manual_comparison_rejects_changed_session_and_keeps_partial(tmp_path, monkeypatch):
    snapshots = iter([
        {"session": {"id": "p", "token": "one"}, "tracks": [], "fx_nonempty": False},
        {"session": {"id": "p", "token": "two"}, "tracks": [], "fx_nonempty": False},
    ])
    setup_probe(monkeypatch, lambda _: next(snapshots))
    evidence = probe.run(args(tmp_path, manual_fader=True), input_fn=lambda _: "")
    assert evidence["ok"] is False
    evidence = json.loads((tmp_path / "evidence.json").read_text())
    assert evidence["ok"] is False
    assert evidence["manual_fader"]["before"]["session"]["token"] == "one"


def test_main_returns_failure_for_failed_evidence(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(probe, "run", lambda args: {"ok": False, "error": "session changed"})
    rc = probe.main(["--controller", str(tmp_path), "--output", str(tmp_path / "out.json")])
    assert rc == 1
    assert "session changed" in capsys.readouterr().out
