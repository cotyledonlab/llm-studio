"""Bounded, process-isolated render job supervision.

Workers render into a private directory.  Only the supervising parent process
can publish that directory at the requested immutable result path.
"""

from __future__ import annotations

import ctypes
import errno
import multiprocessing
import os
import resource
import shutil
import signal
import sys
import tempfile
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any, Callable, Mapping


UTC = timezone.utc
Worker = Callable[["RenderJob", Path], None]


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    TIMING_OUT = "timing_out"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"

    @property
    def terminal(self) -> bool:
        return self in {
            JobState.SUCCEEDED,
            JobState.FAILED,
            JobState.CANCELLED,
            JobState.TIMED_OUT,
        }


@dataclass(frozen=True)
class ResourceLimits:
    """Per-worker operating-system limits.

    A value of ``None`` leaves the corresponding host limit unchanged.
    """

    cpu_seconds: int | None = None
    memory_bytes: int | None = None

    def __post_init__(self) -> None:
        if self.cpu_seconds is not None and self.cpu_seconds <= 0:
            raise ValueError("cpu_seconds must be positive")
        if self.memory_bytes is not None and self.memory_bytes <= 0:
            raise ValueError("memory_bytes must be positive")


@dataclass(frozen=True)
class RenderJob:
    """Complete, persistable envelope for one offline render."""

    job_id: str
    arrangement_revision: str
    performance_hash: str
    backend_version: str
    instrument_state_hash: str
    sample_rate: int
    channel_layout: str
    start_position_s: float
    end_position_s: float
    preroll_s: float
    tail_s: float
    deterministic_seed: int | None
    limits: ResourceLimits
    deadline_at: datetime
    result_path: Path
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.job_id:
            raise ValueError("job_id must not be empty")
        if (
            self.deadline_at.tzinfo is None
            or self.deadline_at.utcoffset() != UTC.utcoffset(None)
        ):
            raise ValueError("deadline_at must be a timezone-aware UTC datetime")
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if self.start_position_s < 0 or self.end_position_s <= self.start_position_s:
            raise ValueError("end_position_s must be after the nonnegative start_position_s")
        if self.preroll_s < 0 or self.tail_s < 0:
            raise ValueError("preroll_s and tail_s must be nonnegative")
        object.__setattr__(self, "deadline_at", self.deadline_at.astimezone(UTC))
        object.__setattr__(self, "result_path", Path(self.result_path).expanduser().resolve())


@dataclass(frozen=True)
class JobStatus:
    job_id: str
    state: JobState
    deadline_at: datetime
    submitted_at: datetime
    started_at: datetime | None
    cancellation_acknowledged_at: datetime | None
    finished_at: datetime | None
    worker_pid: int | None
    limit_observations: Mapping[str, str]
    error: str | None
    result_path: Path | None


@dataclass
class _Record:
    job: RenderJob
    worker: Worker
    state: JobState = JobState.QUEUED
    submitted_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    cancellation_acknowledged_at: datetime | None = None
    finished_at: datetime | None = None
    process: multiprocessing.Process | None = None
    connection: Connection | None = None
    worker_pid: int | None = None
    worker_pgid: int | None = None
    limit_observations: dict[str, str] = field(default_factory=dict)
    worker_completed_at: datetime | None = None
    worker_succeeded: bool = False
    worker_error: str | None = None
    stop_started_monotonic: float | None = None
    work_root: Path | None = None
    output_path: Path | None = None
    error: str | None = None


def _set_limit(kind: int, requested: int) -> None:
    _, hard = resource.getrlimit(kind)
    value = requested if hard == resource.RLIM_INFINITY else min(requested, hard)
    # Some Darwin limits report an unsigned infinity that cannot be passed
    # back through setrlimit. Workers never need to raise their own budget, so
    # make the requested value both the soft and hard child-process limit.
    resource.setrlimit(kind, (value, value))


def _apply_resource_limits(limits: ResourceLimits) -> dict[str, str]:
    observations: dict[str, str] = {}
    if limits.cpu_seconds is not None:
        _set_limit(resource.RLIMIT_CPU, limits.cpu_seconds)
        observations["cpu"] = "kernel-enforced"
    if limits.memory_bytes is not None:
        try:
            _set_limit(resource.RLIMIT_AS, limits.memory_bytes)
            observations["memory"] = "kernel-enforced-address-space"
        except (OSError, ValueError):
            # macOS exposes RLIMIT_AS but rejects changes on current systems.
            # RLIMIT_RSS is the available per-process resident-memory budget;
            # qualification must still measure whether the host enforces it.
            try:
                if not hasattr(resource, "RLIMIT_RSS"):
                    raise ValueError("RLIMIT_RSS is unavailable")
                _set_limit(resource.RLIMIT_RSS, limits.memory_bytes)
                observations["memory"] = "kernel-advisory-resident-set"
            except (OSError, ValueError) as exc:
                observations["memory"] = f"not-enforced-by-host: {exc}"
    return observations


def _worker_main(worker: Worker, job: RenderJob, output: Path, connection: Connection) -> None:
    """Child entry point; worker output remains private until parent publication."""

    try:
        os.setsid()
        limit_observations = _apply_resource_limits(job.limits)
        connection.send(
            {
                "kind": "started",
                "pid": os.getpid(),
                "pgid": os.getpgrp(),
                "limit_observations": limit_observations,
            }
        )
        worker(job, output)
        if not output.is_dir():
            raise RuntimeError("render worker did not create its output directory")
        connection.send(
            {
                "kind": "succeeded",
                "completed_at": datetime.now(UTC).isoformat(),
            }
        )
    except BaseException:
        try:
            connection.send(
                {
                    "kind": "failed",
                    "completed_at": datetime.now(UTC).isoformat(),
                    "error": traceback.format_exc(limit=12),
                }
            )
        except (BrokenPipeError, EOFError, OSError):
            pass
        raise
    finally:
        connection.close()


class RenderService:
    """Supervise bounded render workers and own immutable publication."""

    def __init__(
        self,
        *,
        max_workers: int = 2,
        cancel_grace_s: float = 4.0,
        poll_interval_s: float = 0.01,
        start_method: str = "spawn",
    ) -> None:
        if max_workers <= 0:
            raise ValueError("max_workers must be positive")
        if cancel_grace_s < 0:
            raise ValueError("cancel_grace_s must be nonnegative")
        self.max_workers = max_workers
        self.cancel_grace_s = cancel_grace_s
        self.poll_interval_s = poll_interval_s
        self._context = multiprocessing.get_context(start_method)
        self._records: dict[str, _Record] = {}
        self._queue: deque[str] = deque()
        self._condition = threading.Condition(threading.RLock())
        self._closing = False
        self._supervisor = threading.Thread(
            target=self._supervise,
            name="render-job-supervisor",
            daemon=True,
        )
        self._supervisor.start()

    def __enter__(self) -> "RenderService":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def submit(self, job: RenderJob, worker: Worker) -> JobStatus:
        with self._condition:
            if self._closing:
                raise RuntimeError("render service is closed")
            if job.job_id in self._records:
                raise ValueError(f"duplicate render job id: {job.job_id}")
            if job.result_path.exists() or job.result_path.is_symlink():
                raise FileExistsError(f"immutable render result already exists: {job.result_path}")
            record = _Record(job=job, worker=worker)
            self._records[job.job_id] = record
            self._queue.append(job.job_id)
            self._advance_locked()
            self._condition.notify_all()
            return self._snapshot(record)

    def status(self, job_id: str) -> JobStatus:
        with self._condition:
            record = self._record(job_id)
            self._advance_locked()
            return self._snapshot(record)

    def wait(self, job_id: str, *, timeout: float | None = None) -> JobStatus:
        stop = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            record = self._record(job_id)
            while not record.state.terminal:
                remaining = None if stop is None else stop - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise TimeoutError(f"render job {job_id} did not finish within {timeout}s")
                self._condition.wait(remaining)
            return self._snapshot(record)

    def cancel(self, job_id: str) -> JobStatus:
        """Acknowledge cancellation and begin stopping the isolated process group."""

        with self._condition:
            record = self._record(job_id)
            if record.state.terminal:
                return self._snapshot(record)
            now = datetime.now(UTC)
            record.cancellation_acknowledged_at = now
            if record.state is JobState.QUEUED:
                record.state = JobState.CANCELLED
                record.finished_at = now
                record.error = "cancelled before worker admission"
                self._discard_from_queue(record.job.job_id)
            else:
                self._drain_messages(record)
                record.state = JobState.CANCELLING
                record.stop_started_monotonic = time.monotonic()
                record.error = "cancellation requested"
                self._signal(record, signal.SIGTERM)
            self._condition.notify_all()
            return self._snapshot(record)

    def close(self) -> None:
        with self._condition:
            if self._closing:
                return
            self._closing = True
            for record in self._records.values():
                if not record.state.terminal:
                    self.cancel(record.job.job_id)
            self._condition.notify_all()
        deadline = time.monotonic() + self.cancel_grace_s + 2.0
        while time.monotonic() < deadline:
            with self._condition:
                if all(record.state.terminal for record in self._records.values()):
                    break
            time.sleep(self.poll_interval_s)
        with self._condition:
            for record in self._records.values():
                if record.process is not None and record.process.is_alive():
                    self._signal(record, signal.SIGKILL)
            self._condition.notify_all()
        self._supervisor.join(timeout=1.0)

    def _record(self, job_id: str) -> _Record:
        try:
            return self._records[job_id]
        except KeyError as exc:
            raise KeyError(f"unknown render job id: {job_id}") from exc

    def _snapshot(self, record: _Record) -> JobStatus:
        return JobStatus(
            job_id=record.job.job_id,
            state=record.state,
            deadline_at=record.job.deadline_at,
            submitted_at=record.submitted_at,
            started_at=record.started_at,
            cancellation_acknowledged_at=record.cancellation_acknowledged_at,
            finished_at=record.finished_at,
            worker_pid=record.worker_pid,
            limit_observations=dict(record.limit_observations),
            error=record.error,
            result_path=record.job.result_path if record.state is JobState.SUCCEEDED else None,
        )

    def _supervise(self) -> None:
        while True:
            with self._condition:
                self._advance_locked()
                if self._closing and all(
                    record.state.terminal for record in self._records.values()
                ):
                    return
                self._condition.wait(self.poll_interval_s)

    def _advance_locked(self) -> None:
        now = datetime.now(UTC)
        for record in self._records.values():
            if record.process is not None and not record.state.terminal:
                self._drain_messages(record)
                completed_in_time = (
                    record.worker_succeeded
                    and record.worker_completed_at is not None
                    and record.worker_completed_at <= record.job.deadline_at
                )
                if (
                    record.state is JobState.RUNNING
                    and now >= record.job.deadline_at
                    and not completed_in_time
                ):
                    record.state = JobState.TIMING_OUT
                    record.stop_started_monotonic = time.monotonic()
                    record.error = "absolute deadline exceeded"
                    self._signal(record, signal.SIGTERM)
                if (
                    record.state in {JobState.CANCELLING, JobState.TIMING_OUT}
                    and record.stop_started_monotonic is not None
                    and time.monotonic() - record.stop_started_monotonic >= self.cancel_grace_s
                    and record.process.is_alive()
                ):
                    self._signal(record, signal.SIGKILL)
                if not record.process.is_alive():
                    record.process.join(timeout=0)
                    self._drain_messages(record)
                    stopping = record.state in {
                        JobState.CANCELLING,
                        JobState.TIMING_OUT,
                    }
                    grace_elapsed = (
                        record.stop_started_monotonic is not None
                        and time.monotonic() - record.stop_started_monotonic
                        >= self.cancel_grace_s
                    )
                    if stopping and self._process_group_exists(record):
                        if not grace_elapsed:
                            continue
                        self._signal(record, signal.SIGKILL)
                    self._finish_stopped_record(record)

        for job_id in tuple(self._queue):
            record = self._records[job_id]
            if now >= record.job.deadline_at:
                record.state = JobState.TIMED_OUT
                record.finished_at = now
                record.error = "absolute deadline expired before worker admission"
                self._discard_from_queue(job_id)

        active = sum(
            record.process is not None and not record.state.terminal
            for record in self._records.values()
        )
        while self._queue and active < self.max_workers and not self._closing:
            record = self._records[self._queue.popleft()]
            if record.state is not JobState.QUEUED:
                continue
            self._start(record)
            active += 1
        self._condition.notify_all()

    def _start(self, record: _Record) -> None:
        job = record.job
        job.result_path.parent.mkdir(parents=True, exist_ok=True)
        record.work_root = Path(
            tempfile.mkdtemp(
                prefix=f".{job.result_path.name}.{job.job_id}.",
                dir=job.result_path.parent,
            )
        )
        record.output_path = record.work_root / "result"
        receive, send = self._context.Pipe(duplex=False)
        process = self._context.Process(
            target=_worker_main,
            args=(record.worker, job, record.output_path, send),
            name=f"render-{job.job_id}",
        )
        try:
            process.start()
        except BaseException:
            receive.close()
            send.close()
            self._cleanup(record)
            record.state = JobState.FAILED
            record.finished_at = datetime.now(UTC)
            record.error = traceback.format_exc(limit=12)
            return
        send.close()
        record.connection = receive
        record.process = process
        record.worker_pid = process.pid
        record.state = JobState.RUNNING
        record.started_at = datetime.now(UTC)

    def _drain_messages(self, record: _Record) -> None:
        connection = record.connection
        if connection is None:
            return
        try:
            while connection.poll():
                message = connection.recv()
                if message["kind"] == "started":
                    pid = int(message["pid"])
                    pgid = int(message["pgid"])
                    if pid == record.worker_pid and pgid == pid:
                        record.worker_pgid = pgid
                    record.limit_observations = dict(message["limit_observations"])
                elif message["kind"] == "succeeded":
                    record.worker_succeeded = True
                    record.worker_completed_at = datetime.fromisoformat(
                        message["completed_at"]
                    ).astimezone(UTC)
                elif message["kind"] == "failed":
                    record.worker_completed_at = datetime.fromisoformat(
                        message["completed_at"]
                    ).astimezone(UTC)
                    record.worker_error = str(message["error"])
        except (EOFError, OSError):
            connection.close()
            record.connection = None

    def _finish_stopped_record(self, record: _Record) -> None:
        assert record.process is not None
        now = datetime.now(UTC)
        if record.cancellation_acknowledged_at is not None:
            record.state = JobState.CANCELLED
            record.error = "cancelled; isolated worker stopped without publication"
        elif record.state is JobState.TIMING_OUT:
            record.state = JobState.TIMED_OUT
            record.error = "absolute deadline exceeded; isolated worker stopped"
        elif record.process.exitcode != 0:
            record.state = JobState.FAILED
            record.error = record.worker_error or (
                f"render worker exited with exit code {record.process.exitcode}"
            )
        elif record.worker_error is not None:
            record.state = JobState.FAILED
            record.error = record.worker_error
        elif not record.worker_succeeded:
            record.state = JobState.FAILED
            record.error = "render worker exited without a completion message"
        elif (
            record.worker_completed_at is None
            or record.worker_completed_at > record.job.deadline_at
        ):
            record.state = JobState.TIMED_OUT
            record.error = "render worker completed after its absolute deadline"
        else:
            try:
                self._publish(record)
            except BaseException:
                record.state = JobState.FAILED
                record.error = traceback.format_exc(limit=12)
            else:
                record.state = JobState.SUCCEEDED
                record.error = None
        record.finished_at = now
        if record.connection is not None:
            record.connection.close()
            record.connection = None
        self._cleanup(record)

    def _publish(self, record: _Record) -> None:
        assert record.output_path is not None
        if not record.output_path.is_dir() or record.output_path.is_symlink():
            raise RuntimeError("render worker output is not a real directory")
        _rename_no_replace(record.output_path, record.job.result_path)
        _fsync_directory(record.job.result_path.parent)

    def _cleanup(self, record: _Record) -> None:
        if record.work_root is not None and record.work_root.exists():
            shutil.rmtree(record.work_root)

    def _discard_from_queue(self, job_id: str) -> None:
        try:
            self._queue.remove(job_id)
        except ValueError:
            pass

    def _signal(self, record: _Record, requested_signal: signal.Signals) -> None:
        process = record.process
        if process is None:
            return
        try:
            if record.worker_pgid == record.worker_pid and record.worker_pgid is not None:
                os.killpg(record.worker_pgid, requested_signal)
            elif not process.is_alive():
                return
            elif requested_signal is signal.SIGKILL and hasattr(process, "kill"):
                process.kill()
            else:
                process.terminate()
        except ProcessLookupError:
            pass

    def _process_group_exists(self, record: _Record) -> bool:
        if record.worker_pgid != record.worker_pid or record.worker_pgid is None:
            return False
        try:
            os.killpg(record.worker_pgid, 0)
        except ProcessLookupError:
            return False
        return True


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _rename_no_replace(source: Path, destination: Path) -> None:
    """Atomically publish a directory without replacing a prior result."""

    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if sys.platform == "darwin":
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        arguments = (source_bytes, destination_bytes, 0x00000004)
    elif sys.platform.startswith("linux"):
        rename = libc.renameat2
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        arguments = (-100, source_bytes, -100, destination_bytes, 0x00000001)
    else:
        raise OSError(
            errno.ENOTSUP,
            f"atomic no-replace publication unsupported on {sys.platform}",
        )
    rename.restype = ctypes.c_int
    ctypes.set_errno(0)
    if rename(*arguments) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))
