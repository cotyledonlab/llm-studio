from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from llm_studio.render_jobs import JobState, RenderJob, RenderService, ResourceLimits


def _successful_worker(job: RenderJob, output: Path) -> None:
    output.mkdir()
    (output / "worker.json").write_text(
        json.dumps({"job_id": job.job_id, "pid": os.getpid()})
    )


def _sleeping_worker(job: RenderJob, output: Path) -> None:
    Path(job.payload["started_path"]).write_text(str(os.getpid()))
    time.sleep(float(job.payload["sleep_s"]))
    _successful_worker(job, output)


def _hanging_worker(job: RenderJob, output: Path) -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    child_code = (
        "import pathlib,signal,time;"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
        "time.sleep(0.8);"
        f"pathlib.Path({job.payload['child_late_path']!r}).write_text('escaped')"
    )
    subprocess.Popen([sys.executable, "-c", child_code])
    Path(job.payload["started_path"]).write_text(str(os.getpid()))
    while True:
        time.sleep(0.1)


def _successful_worker_with_live_child(job: RenderJob, output: Path) -> None:
    child_code = (
        "import pathlib,signal,time;"
        f"pathlib.Path({job.payload['child_started_path']!r}).write_text('started');"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        "time.sleep(0.6);"
        f"pathlib.Path({job.payload['child_late_path']!r}).write_text('escaped')"
    )
    subprocess.Popen([sys.executable, "-c", child_code])
    _successful_worker(job, output)


def _late_worker(job: RenderJob, output: Path) -> None:
    signal.signal(signal.SIGTERM, lambda *_: None)
    Path(job.payload["started_path"]).write_text(str(os.getpid()))
    time.sleep(0.3)
    _successful_worker(job, output)


def _crashing_worker(job: RenderJob, output: Path) -> None:
    os._exit(17)


def _crashing_worker_with_live_child(job: RenderJob, output: Path) -> None:
    child_code = (
        "import pathlib,time;"
        "time.sleep(0.6);"
        f"pathlib.Path({job.payload['child_late_path']!r}).write_text('escaped')"
    )
    subprocess.Popen([sys.executable, "-c", child_code])
    Path(job.payload["started_path"]).write_text("started")
    os._exit(17)


def _job(tmp_path: Path, job_id: str, *, deadline_in_s: float = 5.0, **payload) -> RenderJob:
    return RenderJob(
        job_id=job_id,
        arrangement_revision="arrangement-7",
        performance_hash="performance-sha256",
        backend_version="test-worker/1",
        instrument_state_hash="state-sha256",
        sample_rate=48_000,
        channel_layout="stereo",
        start_position_s=0.25,
        end_position_s=2.25,
        preroll_s=0.25,
        tail_s=0.5,
        deterministic_seed=42,
        limits=ResourceLimits(cpu_seconds=10, memory_bytes=8 * 1024 * 1024 * 1024),
        deadline_at=datetime.now(timezone.utc) + timedelta(seconds=deadline_in_s),
        result_path=tmp_path / job_id,
        payload=payload,
    )


def _wait_for(path: Path, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out waiting for {path}")
        time.sleep(0.01)


def test_success_runs_out_of_process_and_only_then_publishes(tmp_path: Path) -> None:
    with RenderService(max_workers=2) as service:
        job = _job(tmp_path, "success")
        service.submit(job, _successful_worker)

        result = service.wait(job.job_id, timeout=3)

    assert result.state is JobState.SUCCEEDED
    assert result.started_at is not None
    assert result.finished_at is not None
    assert result.error is None
    assert result.limit_observations["cpu"] == "kernel-enforced"
    assert result.limit_observations["memory"] in {
        "kernel-enforced-address-space",
        "kernel-advisory-resident-set",
    } or result.limit_observations["memory"].startswith("not-enforced-by-host:")
    worker = json.loads((job.result_path / "worker.json").read_text())
    assert worker == {"job_id": job.job_id, "pid": result.worker_pid}
    assert worker["pid"] != os.getpid()


def test_successful_worker_cannot_publish_while_child_process_is_running(
    tmp_path: Path,
) -> None:
    child_started = tmp_path / "child.started"
    child_late = tmp_path / "child-escaped"
    second_started = tmp_path / "second.started"
    with RenderService(max_workers=1, cancel_grace_s=0.2) as service:
        job = _job(
            tmp_path,
            "leaked-child",
            child_started_path=str(child_started),
            child_late_path=str(child_late),
        )
        service.submit(job, _successful_worker_with_live_child)
        _wait_for(child_started)
        second = _job(
            tmp_path,
            "after-leak",
            started_path=str(second_started),
            sleep_s=0.01,
        )
        queued = service.submit(second, _sleeping_worker)
        assert queued.state is JobState.QUEUED
        time.sleep(0.05)
        assert service.status(job.job_id).state is JobState.RUNNING
        assert not second_started.exists()
        result = service.wait(job.job_id, timeout=3)
        second_result = service.wait(second.job_id, timeout=3)

    assert result.state is JobState.FAILED
    assert "left subprocesses running" in (result.error or "")
    assert not job.result_path.exists()
    assert second_result.state is JobState.SUCCEEDED
    time.sleep(0.7)
    assert not child_late.exists()


def test_default_admission_limit_runs_two_jobs_and_queues_the_third(tmp_path: Path) -> None:
    first_started = tmp_path / "first.started"
    second_started = tmp_path / "second.started"
    third_started = tmp_path / "third.started"
    with RenderService() as service:
        service.submit(
            _job(tmp_path, "first", started_path=str(first_started), sleep_s=0.4),
            _sleeping_worker,
        )
        service.submit(
            _job(tmp_path, "second", started_path=str(second_started), sleep_s=0.4),
            _sleeping_worker,
        )
        service.submit(
            _job(tmp_path, "third", started_path=str(third_started), sleep_s=0.01),
            _sleeping_worker,
        )

        _wait_for(first_started)
        _wait_for(second_started)
        assert service.status("first").state is JobState.RUNNING
        assert service.status("second").state is JobState.RUNNING
        assert service.status("third").state is JobState.QUEUED
        assert not third_started.exists()

        assert service.wait("first", timeout=3).state is JobState.SUCCEEDED
        assert service.wait("second", timeout=3).state is JobState.SUCCEEDED
        assert service.wait("third", timeout=3).state is JobState.SUCCEEDED


def test_host_admission_pause_keeps_worker_queued_until_pressure_clears(tmp_path: Path) -> None:
    admitted = False

    def can_start(_: RenderJob) -> bool:
        return admitted

    with RenderService(admission_check=can_start) as service:
        job = _job(tmp_path, "pressure")
        assert service.submit(job, _successful_worker).state is JobState.QUEUED
        time.sleep(0.05)
        assert not job.result_path.exists()
        admitted = True
        assert service.wait(job.job_id, timeout=3).state is JobState.SUCCEEDED


def test_admission_probe_error_fails_one_job_without_stopping_supervisor(tmp_path: Path) -> None:
    def broken(_: RenderJob) -> bool:
        raise RuntimeError("memory monitor unavailable")

    with RenderService(admission_check=broken) as service:
        job = _job(tmp_path, "probe-error")
        result = service.submit(job, _successful_worker)

    assert result.state is JobState.FAILED
    assert "memory monitor unavailable" in (result.error or "")
    assert not job.result_path.exists()


def test_absolute_deadline_terminates_hung_process_group_without_publication(
    tmp_path: Path,
) -> None:
    started = tmp_path / "hung.started"
    child_late = tmp_path / "child-escaped"
    with RenderService(cancel_grace_s=0.1) as service:
        job = _job(
            tmp_path,
            "hung",
            deadline_in_s=0.35,
            started_path=str(started),
            child_late_path=str(child_late),
        )
        service.submit(job, _hanging_worker)
        _wait_for(started)

        result = service.wait(job.job_id, timeout=3)

    assert result.state is JobState.TIMED_OUT
    assert result.deadline_at == job.deadline_at
    assert result.finished_at is not None
    assert "deadline" in (result.error or "")
    assert not job.result_path.exists()
    time.sleep(0.9)
    assert not child_late.exists()


def test_cancellation_waits_for_term_ignoring_child_to_stop(tmp_path: Path) -> None:
    started = tmp_path / "cancel-hung.started"
    child_late = tmp_path / "cancel-child-escaped"
    with RenderService(cancel_grace_s=0.1) as service:
        job = _job(
            tmp_path,
            "cancel-hung",
            started_path=str(started),
            child_late_path=str(child_late),
        )
        service.submit(job, _hanging_worker)
        _wait_for(started)
        service.cancel(job.job_id)
        result = service.wait(job.job_id, timeout=3)

    assert result.state is JobState.CANCELLED
    assert not job.result_path.exists()
    time.sleep(0.9)
    assert not child_late.exists()


def test_close_stays_bounded_when_term_ignoring_child_needs_kill(tmp_path: Path) -> None:
    started = tmp_path / "close-hung.started"
    child_late = tmp_path / "close-child-escaped"
    service = RenderService(cancel_grace_s=0.1)
    job = _job(
        tmp_path,
        "close-hung",
        started_path=str(started),
        child_late_path=str(child_late),
    )
    service.submit(job, _hanging_worker)
    _wait_for(started)

    before = time.monotonic()
    service.close()
    assert time.monotonic() - before < 3.5
    result = service.status(job.job_id)
    assert result.state is not JobState.SUCCEEDED
    assert not job.result_path.exists()
    time.sleep(0.9)
    assert not child_late.exists()


def test_cancellation_is_acknowledged_quickly_and_late_success_cannot_publish(
    tmp_path: Path,
) -> None:
    started = tmp_path / "late.started"
    with RenderService(cancel_grace_s=0.5) as service:
        job = _job(tmp_path, "cancelled", started_path=str(started))
        service.submit(job, _late_worker)
        _wait_for(started)

        before = time.monotonic()
        acknowledgement = service.cancel(job.job_id)
        elapsed = time.monotonic() - before
        result = service.wait(job.job_id, timeout=3)

    assert elapsed < 1.0
    assert acknowledgement.cancellation_acknowledged_at is not None
    assert acknowledgement.state in {JobState.CANCELLING, JobState.CANCELLED}
    assert result.state is JobState.CANCELLED
    assert result.finished_at is not None
    assert not job.result_path.exists()


def test_worker_crash_is_reported_as_failure_not_success(tmp_path: Path) -> None:
    with RenderService() as service:
        job = _job(tmp_path, "crash")
        service.submit(job, _crashing_worker)

        result = service.wait(job.job_id, timeout=3)

    assert result.state is JobState.FAILED
    assert "exit code 17" in (result.error or "")
    assert not job.result_path.exists()


def test_crashing_worker_cannot_leave_a_child_writing_after_failure(
    tmp_path: Path,
) -> None:
    started = tmp_path / "crash-child.started"
    child_late = tmp_path / "crash-child-escaped"
    with RenderService(cancel_grace_s=0.1) as service:
        job = _job(
            tmp_path,
            "crash-with-child",
            started_path=str(started),
            child_late_path=str(child_late),
        )
        service.submit(job, _crashing_worker_with_live_child)
        _wait_for(started)
        result = service.wait(job.job_id, timeout=3)

    assert result.state is JobState.FAILED
    assert "exit code 17" in (result.error or "")
    assert not job.result_path.exists()
    time.sleep(0.7)
    assert not child_late.exists()


def test_expired_job_never_starts(tmp_path: Path) -> None:
    with RenderService() as service:
        job = _job(tmp_path, "expired", deadline_in_s=-1)
        result = service.submit(job, _successful_worker)

        result = service.wait(job.job_id, timeout=1)

    assert result.state is JobState.TIMED_OUT
    assert result.worker_pid is None
    assert not job.result_path.exists()


def test_job_envelope_requires_utc_deadline_and_valid_timeline(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        RenderJob(
            **{
                **_job(tmp_path, "valid").__dict__,
                "deadline_at": datetime.now(),
            }
        )

    with pytest.raises(ValueError, match="end_position_s"):
        RenderJob(
            **{
                **_job(tmp_path, "valid-2").__dict__,
                "end_position_s": 0.1,
            }
        )
