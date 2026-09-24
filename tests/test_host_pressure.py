from __future__ import annotations

import json
import time
from pathlib import Path

from llm_studio.host_pressure import HostPressureMonitor


def _write_probe(path: Path, *, age_s: float = 0.0, **overrides: object) -> None:
    row = {
        "probe_running": True,
        "audio_xrun_events": 0,
        "media_xrun_events": 0,
        "latest_audio_xrun_age_ms": None,
    }
    row.update(overrides)
    path.write_text(json.dumps(row) + "\n")
    if age_s:
        old = time.time() - age_s
        import os

        os.utime(path, (old, old))


def _wait_for_snapshot(monitor: HostPressureMonitor, *, admitted: bool) -> None:
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        snapshot = monitor.snapshot()
        if snapshot is not None and snapshot.admitted is admitted:
            return
        time.sleep(0.005)
    raise AssertionError(f"monitor did not produce admitted={admitted}: {monitor.snapshot()}")


def test_memory_threshold_and_recent_xrun_control_admission(tmp_path: Path) -> None:
    probe = tmp_path / "probe.jsonl"
    _write_probe(probe)
    monitor = HostPressureMonitor(
        probe, sample_interval_s=0.01, memory_reader=lambda: 9
    )
    with monitor:
        _wait_for_snapshot(monitor, admitted=False)
        assert "memory_free_below_threshold" in monitor.snapshot().reasons

    _write_probe(probe)
    monitor = HostPressureMonitor(
        probe, sample_interval_s=0.01, memory_reader=lambda: 10
    )
    with monitor:
        _wait_for_snapshot(monitor, admitted=True)
        assert monitor.admit(None)

    _write_probe(probe, latest_audio_xrun_age_ms=250)
    monitor = HostPressureMonitor(
        probe, sample_interval_s=0.01, memory_reader=lambda: 30
    )
    with monitor:
        _wait_for_snapshot(monitor, admitted=False)
        assert "recent_audio_xrun" in monitor.snapshot().reasons


def test_stale_missing_stopped_and_malformed_probe_fail_closed(tmp_path: Path) -> None:
    probe = tmp_path / "probe.jsonl"
    for setup, reason in (
        (lambda: None, "reaper_probe_missing_or_stale"),
        (lambda: _write_probe(probe, age_s=5), "reaper_probe_missing_or_stale"),
        (lambda: _write_probe(probe, probe_running=False), "reaper_probe_stopped"),
        (lambda: _write_probe(probe, audio_xrun_events="many"), "sampler_failed"),
    ):
        probe.unlink(missing_ok=True)
        setup()
        monitor = HostPressureMonitor(
            probe, sample_interval_s=0.01, memory_reader=lambda: 30
        )
        with monitor:
            _wait_for_snapshot(monitor, admitted=False)
            assert reason in " ".join(monitor.snapshot().reasons)


def test_stale_green_snapshot_and_sampler_failure_fail_closed(tmp_path: Path) -> None:
    probe = tmp_path / "probe.jsonl"
    _write_probe(probe)
    monitor = HostPressureMonitor(
        probe,
        sample_interval_s=0.01,
        snapshot_max_age_s=0.03,
        memory_reader=lambda: 30,
    )
    with monitor:
        _wait_for_snapshot(monitor, admitted=True)
        original_sample = monitor._sample
        blocked = False

        def stalled_sample() -> None:
            nonlocal blocked
            if not blocked:
                blocked = True
                time.sleep(0.06)
            else:
                original_sample()

        monitor._sample = stalled_sample
        time.sleep(0.04)
        assert not monitor.admit(None)

    monitor = HostPressureMonitor(
        probe, sample_interval_s=0.01, memory_reader=lambda: 30
    )
    monitor._sample = lambda: (_ for _ in ()).throw(RuntimeError("probe crashed"))
    with monitor:
        _wait_for_snapshot(monitor, admitted=False)
        assert "sampler_failed" in " ".join(monitor.snapshot().reasons)
        assert not monitor.admit(None)


def test_evidence_write_failure_blocks_admission(tmp_path: Path) -> None:
    probe = tmp_path / "probe.jsonl"
    _write_probe(probe)
    bad_parent = tmp_path / "not-a-directory"
    bad_parent.write_text("file")
    monitor = HostPressureMonitor(
        probe,
        evidence_path=bad_parent / "evidence.jsonl",
        sample_interval_s=0.01,
        memory_reader=lambda: 30,
    )
    with monitor:
        _wait_for_snapshot(monitor, admitted=False)
        assert "evidence_write_failed" in " ".join(monitor.snapshot().reasons)
