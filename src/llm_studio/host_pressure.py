"""macOS host-memory and REAPER underrun monitor for render admission.

The monitor is intentionally conservative: it admits a queued render only
while its observations are fresh, available memory is above the configured
floor, and no recent audio underrun has been reported by the REAPER probe.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


UTC = timezone.utc
_FREE_RE = re.compile(r"System-wide memory free percentage:\s*(\d+)%")


@dataclass(frozen=True)
class HostPressureSnapshot:
    observed_at: str
    memory_free_percent: int | None
    audio_xrun_events: int | None
    media_xrun_events: int | None
    latest_audio_xrun_age_ms: int | None
    probe_age_s: float | None
    admitted: bool
    reasons: tuple[str, ...]


def memory_free_percent() -> int:
    """Return the host-wide free-memory percentage reported by macOS."""

    result = subprocess.run(
        ["/usr/bin/memory_pressure", "-Q"],
        check=True,
        capture_output=True,
        text=True,
        timeout=2.0,
    )
    match = _FREE_RE.search(result.stdout)
    if match is None:
        raise RuntimeError("memory_pressure output did not include free percentage")
    return int(match.group(1))


def _latest_probe(path: Path) -> tuple[dict | None, float | None]:
    try:
        stat = path.stat()
        with path.open("rb") as stream:
            stream.seek(max(0, stat.st_size - 65536))
            lines = stream.read().splitlines()
    except FileNotFoundError:
        return None, None
    if not lines:
        return None, max(0.0, time.time() - stat.st_mtime)
    try:
        sample = json.loads(lines[-1])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("latest REAPER probe row is malformed") from exc
    if not isinstance(sample, dict) or "audio_xrun_events" not in sample:
        raise ValueError("latest REAPER probe row has an invalid shape")
    return sample, max(0.0, time.time() - stat.st_mtime)


class HostPressureMonitor:
    """Background sampler usable directly as ``RenderService`` admission check.

    REAPER's deferred probe must be running and writing fresh JSONL samples.
    A recent audio xrun suppresses new worker starts for ``xrun_cooldown_s``;
    already-running renders are left to the caller's normal cancellation policy.
    """

    def __init__(
        self,
        reaper_probe_path: Path,
        *,
        evidence_path: Path | None = None,
        minimum_free_percent: int = 10,
        xrun_cooldown_s: float = 30.0,
        sample_interval_s: float = 1.0,
        probe_max_age_s: float = 3.0,
        snapshot_max_age_s: float | None = None,
        memory_reader: Callable[[], int] = memory_free_percent,
    ) -> None:
        if not 0 <= minimum_free_percent <= 100:
            raise ValueError("minimum_free_percent must be from 0 through 100")
        if xrun_cooldown_s < 0 or sample_interval_s <= 0 or probe_max_age_s <= 0:
            raise ValueError("cooldown must be nonnegative and intervals positive")
        self.reaper_probe_path = Path(reaper_probe_path).expanduser().resolve()
        self.evidence_path = (
            Path(evidence_path).expanduser().resolve() if evidence_path else None
        )
        self.minimum_free_percent = minimum_free_percent
        self.xrun_cooldown_s = xrun_cooldown_s
        self.sample_interval_s = sample_interval_s
        self.probe_max_age_s = probe_max_age_s
        self.snapshot_max_age_s = (
            snapshot_max_age_s if snapshot_max_age_s is not None
            else max(3.0 * sample_interval_s, probe_max_age_s)
        )
        if self.snapshot_max_age_s <= 0:
            raise ValueError("snapshot_max_age_s must be positive")
        self.memory_reader = memory_reader
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._snapshot: HostPressureSnapshot | None = None
        self._snapshot_monotonic: float | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> "HostPressureMonitor":
        if self._thread is not None:
            raise RuntimeError("host pressure monitor already started")
        self._thread = threading.Thread(
            target=self._run, name="host-pressure-monitor", daemon=True
        )
        self._thread.start()
        return self

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.5, self.sample_interval_s + 1.0))

    def __enter__(self) -> "HostPressureMonitor":
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.close()

    def snapshot(self) -> HostPressureSnapshot | None:
        with self._lock:
            return self._snapshot

    def admit(self, _job: object) -> bool:
        thread = self._thread
        with self._lock:
            current = self._snapshot
            sampled_at = self._snapshot_monotonic
        if current is None or thread is None or not thread.is_alive() or sampled_at is None:
            return False
        if time.monotonic() - sampled_at > self.snapshot_max_age_s:
            return False
        return current.admitted

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._sample()
            except Exception as exc:
                self._publish_failure(f"sampler_failed:{type(exc).__name__}:{exc}")
            self._stop.wait(self.sample_interval_s)

    def _publish_failure(self, reason: str) -> None:
        value = HostPressureSnapshot(
            observed_at=datetime.now(UTC).isoformat(),
            memory_free_percent=None,
            audio_xrun_events=None,
            media_xrun_events=None,
            latest_audio_xrun_age_ms=None,
            probe_age_s=None,
            admitted=False,
            reasons=(reason,),
        )
        with self._lock:
            self._snapshot = value
            self._snapshot_monotonic = time.monotonic()

    def _sample(self) -> None:
        reasons: list[str] = []
        observed = datetime.now(UTC).isoformat()
        free: int | None
        try:
            free = self.memory_reader()
        except Exception as exc:
            free = None
            reasons.append(f"memory_probe_failed:{type(exc).__name__}:{exc}")
        if free is None or free < self.minimum_free_percent:
            reasons.append("memory_free_below_threshold" if free is not None else "memory_unavailable")

        probe, age = _latest_probe(self.reaper_probe_path)
        if probe is None or age is None or age > self.probe_max_age_s:
            audio_events = media_events = None
            latest_audio_age = None
            reasons.append("reaper_probe_missing_or_stale")
        else:
            if probe.get("probe_running") is not True:
                reasons.append("reaper_probe_stopped")
            audio_events = _integer(probe, "audio_xrun_events")
            media_events = _integer(probe, "media_xrun_events")
            latest_audio_age = _integer(probe, "latest_audio_xrun_age_ms", allow_none=True)
            if latest_audio_age is not None and latest_audio_age < self.xrun_cooldown_s * 1000:
                reasons.append("recent_audio_xrun")

        value = HostPressureSnapshot(
            observed_at=observed,
            memory_free_percent=free,
            audio_xrun_events=audio_events,
            media_xrun_events=media_events,
            latest_audio_xrun_age_ms=latest_audio_age,
            probe_age_s=age,
            admitted=not reasons,
            reasons=tuple(reasons),
        )
        if self.evidence_path is not None:
            try:
                self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
                with self.evidence_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(asdict(value), sort_keys=True) + "\n")
            except Exception as exc:
                value = HostPressureSnapshot(
                    **{
                        **asdict(value),
                        "admitted": False,
                        "reasons": (*value.reasons, f"evidence_write_failed:{type(exc).__name__}:{exc}"),
                    }
                )
        with self._lock:
            self._snapshot = value
            self._snapshot_monotonic = time.monotonic()


def _integer(value: dict, key: str, *, allow_none: bool = False) -> int | None:
    raw = value.get(key)
    if raw is None and allow_none:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or int(raw) != raw:
        raise ValueError(f"invalid {key} in REAPER probe")
    if int(raw) < 0:
        raise ValueError(f"negative {key} in REAPER probe")
    return int(raw)


def resource_probe_path(reaper_resource_path: Path) -> Path:
    """Return the path written by ``reaper_host_pressure_probe.lua``."""

    return Path(reaper_resource_path) / "llm-studio-host-pressure.jsonl"
