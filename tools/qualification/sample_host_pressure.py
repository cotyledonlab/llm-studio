#!/usr/bin/env python3
"""Capture macOS memory admission and REAPER underrun evidence during playback."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from llm_studio.host_pressure import HostPressureMonitor, resource_probe_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reaper-resource-path", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--duration-s", type=float, default=120.0)
    parser.add_argument("--interval-s", type=float, default=1.0)
    parser.add_argument("--minimum-free-percent", type=int, default=10)
    parser.add_argument("--xrun-cooldown-s", type=float, default=30.0)
    args = parser.parse_args()
    if args.duration_s <= 0:
        parser.error("--duration-s must be positive")

    monitor = HostPressureMonitor(
        resource_probe_path(args.reaper_resource_path),
        evidence_path=args.evidence,
        minimum_free_percent=args.minimum_free_percent,
        xrun_cooldown_s=args.xrun_cooldown_s,
        sample_interval_s=args.interval_s,
    )
    stop_at = time.monotonic() + args.duration_s
    with monitor:
        while time.monotonic() < stop_at:
            time.sleep(min(1.0, max(0.0, stop_at - time.monotonic())))
    records = [json.loads(line) for line in args.evidence.read_text().splitlines() if line]
    admitted = sum(record["admitted"] for record in records)
    summary = {
        "samples": len(records),
        "admitted_samples": admitted,
        "paused_samples": len(records) - admitted,
        "minimum_memory_free_percent": min(
            (record["memory_free_percent"] for record in records if record["memory_free_percent"] is not None),
            default=None,
        ),
        "maximum_reaper_probe_age_s": max(
            (record["probe_age_s"] for record in records if record["probe_age_s"] is not None),
            default=None,
        ),
        "pause_reasons": sorted({reason for record in records for reason in record["reasons"]}),
        "evidence": str(args.evidence.resolve()),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
