#!/usr/bin/env python3
"""Qualify the job supervisor with an installed offline instrument worker.

Run once per backend in its pinned Python environment. Results stay outside git.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import signal
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from llm_studio.catalogue import Catalogue
from llm_studio.render_jobs import JobState, RenderJob, RenderService, ResourceLimits
from tools.qualification.catalogue_audition import render_job


def _fault_worker(job: RenderJob, output: Path) -> None:
    mode = job.payload["mode"]
    marker = Path(job.payload["marker"])
    marker.write_text(str(os.getpid()))
    render_job(job, output)
    Path(job.payload["rendered_marker"]).write_text(str(os.getpid()))
    if mode == "crash":
        os._exit(17)
    if mode == "hang":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        while True:
            time.sleep(0.1)


def _job(instrument_id: str, mode: str, root: Path, index: int) -> RenderJob:
    instrument = Catalogue.packaged().get(instrument_id)
    fixture = instrument.fixture
    now = datetime.now(timezone.utc)
    return RenderJob(
        job_id=f"{mode}-{index}",
        arrangement_revision="native-qualification-1",
        performance_hash=instrument.data["audition_fixture_sha256"],
        backend_version=instrument.data["backend"]["version"],
        instrument_state_hash=instrument.data["state_sha256"],
        sample_rate=fixture["sample_rate"],
        channel_layout="stereo",
        start_position_s=fixture["start_s"],
        end_position_s=fixture["start_s"] + fixture["duration_s"],
        preroll_s=0,
        tail_s=fixture["tail_s"],
        deterministic_seed=instrument.data["state"].get("seed"),
        limits=ResourceLimits(cpu_seconds=20, memory_bytes=2 * 1024**3),
        deadline_at=now + timedelta(seconds=3 if mode == "hang" else 15),
        result_path=root / f"{mode}-{index}",
        payload={
            "instrument_id": instrument_id,
            "mode": mode,
            "marker": str(root / f"{mode}-{index}.started"),
            "rendered_marker": str(root / f"{mode}-{index}.rendered"),
        },
    )


def _wait_marker(path: Path, service: RenderService, job_id: str) -> None:
    stop = time.monotonic() + 10
    while not path.exists():
        state = service.status(job_id).state
        if state.terminal or time.monotonic() >= stop:
            raise RuntimeError(f"worker did not start: {job_id} ({state.value})")
        time.sleep(0.005)


def _run(instrument_id: str, root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=False)
    results = []
    with RenderService(cancel_grace_s=0.25) as service:
        for index, mode in enumerate(("success", "success", "crash", "hang", "cancel")):
            job = _job(instrument_id, mode, root, index)
            started = time.monotonic()
            service.submit(job, _fault_worker)
            _wait_marker(Path(job.payload["marker"]), service, job.job_id)
            if mode == "cancel":
                acknowledged = service.cancel(job.job_id)
                assert acknowledged.cancellation_acknowledged_at is not None
            if mode == "hang":
                # Wait for the real renderer to stage an actual take, then
                # let the absolute deadline stop the injected native hang.
                _wait_marker(Path(job.payload["rendered_marker"]), service, job.job_id)
            status = service.wait(job.job_id, timeout=20)
            expected = {
                "success": JobState.SUCCEEDED,
                "crash": JobState.FAILED,
                "hang": JobState.TIMED_OUT,
                "cancel": JobState.CANCELLED,
            }[mode]
            if status.state is not expected:
                raise AssertionError(f"{job.job_id}: expected {expected}, found {status.state}: {status.error}")
            if mode != "success" and job.result_path.exists():
                raise AssertionError(f"{job.job_id}: failed/cancelled job published")
            if mode in {"crash", "hang"} and not Path(job.payload["rendered_marker"]).exists():
                raise AssertionError(f"{job.job_id}: injected fault ran before the real render")
            manifest = json.loads((job.result_path / "manifest.json").read_text()) if mode == "success" else None
            results.append({
                "job_id": job.job_id,
                "state": status.state.value,
                "elapsed_s": time.monotonic() - started,
                "worker_pid": status.worker_pid,
                "limits": dict(status.limit_observations),
                "manifest": manifest,
            })
    first, second = results[:2]
    if first["manifest"]["audio"]["sample_sha256"] != second["manifest"]["audio"]["sample_sha256"]:
        raise AssertionError("restarted real worker did not reproduce decoded samples")
    return {
        "instrument_id": instrument_id,
        "host": platform.platform(),
        "python": platform.python_version(),
        "results": results,
    }


def _concurrent(instrument_ids: tuple[str, str], root: Path) -> list[dict]:
    jobs = [_job(instrument_id, "success", root, index + 10) for index, instrument_id in enumerate(instrument_ids)]
    with RenderService(max_workers=2) as service:
        for job in jobs:
            service.submit(job, _fault_worker)
        statuses = [service.wait(job.job_id, timeout=20) for job in jobs]
    if any(status.state is not JobState.SUCCEEDED for status in statuses):
        raise AssertionError(f"concurrent render failed: {statuses}")
    if len({status.worker_pid for status in statuses}) != 2:
        raise AssertionError("concurrent renders shared a worker process")
    if not (
        statuses[0].started_at < statuses[1].finished_at
        and statuses[1].started_at < statuses[0].finished_at
    ):
        raise AssertionError("render worker lifetimes did not overlap")
    return [
        {
            "instrument_id": instrument_id,
            "worker_pid": status.worker_pid,
            "sample_sha256": json.loads((job.result_path / "manifest.json").read_text())["audio"]["sample_sha256"],
        }
        for instrument_id, job, status in zip(instrument_ids, jobs, statuses)
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("instrument_id")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--concurrent-with")
    args = parser.parse_args()
    report = _run(args.instrument_id, args.root.resolve())
    if args.concurrent_with:
        report["concurrent"] = _concurrent(
            (args.instrument_id, args.concurrent_with), args.root.resolve()
        )
    (args.root / "qualification.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({
        "instrument_id": report["instrument_id"],
        "states": [result["state"] for result in report["results"]],
        "elapsed_s": [round(result["elapsed_s"], 3) for result in report["results"]],
        "sample_sha256": report["results"][0]["manifest"]["audio"]["sample_sha256"],
        "evidence": str(args.root / "qualification.json"),
        "concurrent": report.get("concurrent"),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
