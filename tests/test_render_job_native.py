from __future__ import annotations

from types import SimpleNamespace

import pytest

from tools.qualification.render_job_native import _wait_concurrent


def test_concurrent_wait_uses_one_explicit_budget_for_all_jobs() -> None:
    waits: list[float] = []

    class Service:
        def wait(self, job_id: str, *, timeout: float):
            waits.append(timeout)
            return job_id

    jobs = [SimpleNamespace(job_id="first"), SimpleNamespace(job_id="second")]
    assert _wait_concurrent(Service(), jobs, 60) == ["first", "second"]
    assert len(waits) == 2
    assert all(0 < timeout <= 60 for timeout in waits)


def test_concurrent_wait_timeout_identifies_admission_hold() -> None:
    class Service:
        def wait(self, job_id: str, *, timeout: float):
            raise TimeoutError("timed out")

        def status(self, job_id: str):
            return SimpleNamespace(state=SimpleNamespace(value="queued"))

    jobs = [SimpleNamespace(job_id="first"), SimpleNamespace(job_id="second")]
    with pytest.raises(TimeoutError, match="30.0s.*admission may still be holding"):
        _wait_concurrent(Service(), jobs, 30)
