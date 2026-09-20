from __future__ import annotations

import json
import os
import signal
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
    Path(job.payload["started_path"]).write_text(str(os.getpid()))
    while True:
        time.sleep(0.1)


def _late_worker(job: RenderJob, output: Path) -> None:
    signal.signal(signal.SIGTERM, lambda *_: None)
    Path(job.payload["started_path"]).write_text(str(os.getpid()))
    time.sleep(0.3)
    _successful_worker(job, output)


def _crashing_worker(job: RenderJob, output: Path) -> None:
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
        limits=ResourceLimits(cpu_seconds=10, memory_bytes=256 * 1024 * 1024),
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
    worker = json.loads((job.result_path / "worker.json").read_text())
    assert worker == {"job_id": job.job_id, "pid": result.worker_pid}
    assert worker["pid"] != os.getpid()


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


def test_absolute_deadline_terminates_hung_process_group_without_publication(
    tmp_path: Path,
) -> None:
    started = tmp_path / "hung.started"
    with RenderService(cancel_grace_s=0.1) as service:
        job = _job(
            tmp_path,
            "hung",
            deadline_in_s=0.35,
            started_path=str(started),
        )
        service.submit(job, _hanging_worker)
        _wait_for(started)

        result = service.wait(job.job_id, timeout=3)

    assert result.state is JobState.TIMED_OUT
    assert result.deadline_at == job.deadline_at
    assert result.finished_at is not None
    assert "deadline" in (result.error or "")
    assert not job.result_path.exists()


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
