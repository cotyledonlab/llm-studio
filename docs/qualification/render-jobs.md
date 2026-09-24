# Render job qualification (issue #15)

Date: 2026-09-22. Host: Apple Silicon Mac, macOS 26.5.2. Status: **native
worker isolation and publication pass; full Gate B acceptance remains open**.

The runner at `tools/qualification/render_job_native.py` ran the pinned,
producer-approved catalogue instruments inside `RenderService` worker processes.
It used SuperCollider 3.14.1 build `426edf6` with Supriya 26.9b0 for drums/bass,
and Pedalboard 0.9.24 with Dexed VST3 1.0.1 for keys. Python was 3.14.6.
These were offline renderers and did not open an audio device or manipulate
REAPER. Results remain under `/private/tmp/llm-studio-issue15-native-*-20260922/`.

| Worker | Cold / warm job wall time | CPU (cold / warm) | Peak RSS (cold / warm) | Restart sample hash |
|---|---:|---:|---:|---|
| SuperCollider drums | 0.480 / 0.374 s | 0.307 / 0.275 s | 65.2 / 65.1 MB | `4e4f80a007ef436ae38d0a0fdf51e1c2fc1307d451305775fbb430821e7b14a3` |
| Pedalboard Dexed keys | 0.624 / 0.562 s | 0.446 / 0.443 s | 74.7 / 73.8 MB | `0d8847fea635b5baac2874343afb2aad6eb8bc55d7310ad96235735ab4939288` |

Two fresh processes per instrument reproduced decoded samples exactly. The
SuperCollider drums and bass ran concurrently in distinct worker PIDs with
overlapping lifetimes and retained their separate known sample hashes (A10,
A17 for these exact fixtures). The job limit is two workers by default; a third
queued in the supervisor test. The new admission callback can hold jobs queued
while a host monitor reports memory pressure or xruns, and a failing monitor
fails its job instead of silently admitting it. A host monitor has not yet been
connected or measured during REAPER playback.

For each real backend, the runner rendered into private staging, then injected
a worker crash and an ignored-termination hang. The outcomes were respectively
`failed` and `timed_out` after the three-second deadline; neither published an
output. A cancellation acknowledged after worker startup stopped a real render
in about 0.08 s for drums and 0.10 s for keys and published nothing. The
post-render fault markers prove that the crash and hang injections ran after
real native rendering. Existing tests also exercise a descendant-process hang
and a worker that completes after cancellation (A11). There was no direct DAW
playback/xrun observation during these runs.

CPU time was kernel enforced. On this macOS host both RLIMIT_AS and RLIMIT_RSS
changes were rejected, so the requested 2 GiB per-job memory limit was **not
enforced**. The status reports that fact. Peak RSS was measured after normal
renders, but this does not bound a runaway plugin. A host memory-pressure
monitor plus a measured safe worker count remains required before using two
workers alongside DAW playback.

`stem_alignment.py` provides separate-channel common-timeline placement,
zero-phase finite-sinc sample-rate conversion, zero padding through the longest
tail, and explicit measured-latency compensation. Synthetic mono 44.1 kHz and
stereo 48 kHz transient fixtures, plus a 96-to-48 kHz conversion, align peaks
within one output sample without per-stem normalization. This tests the
algorithm and mixed layouts, **not** the required A07 real-renderer calibration.
The catalogue's 33-sample SuperCollider and 57-sample Dexed onset measurements
are thresholded musical attacks, not isolated reference transients. They must
not be used as automatic latency compensation. A real impulse-like instrument
or plugin path, its patch-specific latency measurement, and a REAPER import
readback are still needed to establish A07 without double compensation.

To repeat native worker evidence, run from the repository root with a new
result directory each time:

```sh
PYTHONPATH=src:. /private/tmp/llm-studio-issue-14-runtime/sc/bin/python \
  tools/qualification/render_job_native.py studio.drums.sc-basic-v1 \
  --concurrent-with studio.bass.sc-pulse-v1 --root /private/tmp/new-sc-job-evidence
PYTHONPATH=src:. /private/tmp/llm-studio-issue-14-runtime/pedalboard/bin/python \
  tools/qualification/render_job_native.py studio.keys.dexed-factory-v1 \
  --root /private/tmp/new-dexed-job-evidence
```

The runtime paths above name existing local environments, not dependencies
bundled with this repository. The retained `qualification.json` and immutable
manifests contain exact audio hashes, versions, timings, and CPU/RSS readings.
This evidence is bounded to the pinned host, plugin, state and fixtures. No
general plugin reproducibility, DAW responsiveness, or memory safety is claimed.

## Playback pressure sampler

The Gate B monitor reads the macOS `memory_pressure -Q` free-memory
percentage and a read-only REAPER ReaScript probe. REAPER documents
`GetUnderrunTime()` as the last audio/media underrun timestamps and current
time, all in milliseconds. The deferred probe checks callback delay on every
REAPER cycle, samples underrun timestamps every 100 ms, and records
timestamp changes observed, the latest audio underrun age, and the largest
delay between deferred callbacks. Timestamp age uses unsigned 32-bit
millisecond wrap arithmetic; observed timestamp changes are a lower bound if
multiple events land between polls. The monitor pauses new job
admission below 10% free memory, for 30 seconds after an audio underrun, or
when either observation is missing or stale. These are conservative starting
thresholds for qualification, not measured safe limits. Already-running jobs
are not stopped by an admission pause.

Run `tools/qualification/reaper_host_pressure_probe.lua` in the disposable
REAPER profile while playback is active. It appends
`llm-studio-host-pressure.jsonl` under that profile's resource directory. Run
`reaper_host_pressure_probe_stop.lua` to stop sampling. The startup row is
marked non-admitting until the first native sample arrives. Preserve the resource
path and profile identity in the qualification record; do not run the probe in
the producer-owned session.

While that probe is active, compare one and two worker runs using the same
fixture pair and fresh result/evidence paths:

```sh
PYTHONPATH=src:. python tools/qualification/render_job_native.py studio.drums.sc-basic-v1 \
  --concurrent-with studio.bass.sc-pulse-v1 --max-workers 1 \
  --reaper-resource-path /path/to/disposable/reaper-resource \
  --pressure-evidence /private/tmp/gate-b-one-worker-pressure.jsonl \
  --root /private/tmp/gate-b-one-worker
```

Repeat with `--max-workers 2` and new paths. The qualification report records
worker start/end times and outcomes; the pressure log records free-memory
percentage, observed xrun timestamp changes, probe age, and admission decisions. Compare playback
continuity and producer control responsiveness in REAPER alongside those
records. A zero-xrun result and small deferred-loop gaps are required for the
selected worker count. The monitor does not claim to measure audible quality
or substitute for the producer's playback observation.

`HostPressureMonitor` is also available as a live admission callback:

```python
with HostPressureMonitor(reaper_probe_path, evidence_path=pressure_log) as pressure:
    with RenderService(max_workers=1, admission_check=pressure.admit) as service:
        ...
```

The host monitor is macOS-specific. Its free-memory percentage is an admission
signal, not a per-process memory limit; the existing macOS worker memory-limit
gap remains open.
