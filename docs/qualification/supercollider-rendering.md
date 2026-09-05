# SuperCollider isolated-render qualification (issue #12)

Date: 2026-09-05. Host: Apple Silicon Mac, macOS 26.5.2. Result: **adopt the
NRT engine pattern, but do not adopt the connector's current render API as the
studio job contract**.

## What was inspected

The user-authorized adjacent checkout was
`/Users/johnmaher/code/supercollider-connector`, commit
`d3d7c326d5686e294823824f0f2695b06b3d0cd3`, package version 0.1.0. It declares
MIT in `pyproject.toml`; no standalone licence file was present. The installed
dependencies used here declare MIT (Supriya) and BSD-3-Clause/0BSD/MIT/Zlib/
CC0-1.0 (NumPy). SuperCollider is distributed under GPL-3.0-or-later; that does
not impose a licence on audio rendered with it, but redistribution of the
engine must preserve its licence obligations. No samples or third-party UGens
were used.

Reusable pieces and findings:

- `engine.render` proves the right isolation boundary: Supriya builds a full
  score and invokes `scsynth -N`; no realtime server, GUI, OSC timing loop, or
  audio-device acquisition is involved.
- `synths.py` contains useful SynthDef construction patterns. Its public
  templates are continuous drones, however, not note/phrase instruments.
- `audio.py` has useful basic WAV measurements, but the studio needs
  sample-position measurements and content/state hashes as well.
- `docs/pitfalls.md` records valuable SC 3.14 NRT failures: `SendReply`,
  `Limiter`, and `RecordBuf` can crash NRT. The qualification SynthDef avoids
  all three.
- The connector persists live-server PIDs, not instrument patch state or
  immutable render manifests. Its render method also hard-codes stereo PCM16,
  relies on Supriya's 44.1 kHz render default, renders one drone at time zero,
  publishes directly to its destination, and does not use its `duration_s` as
  a musical phrase boundary. These limits must remain visible.

There is no remote source URL or immutable dependency reference in the
adjacent checkout, so reuse by filesystem import would not be reproducible.
Before integration, publish/tag it or move the small NRT adapter into this
repository with provenance and tests.

## Actual probe

The checked-in probe wraps an explicit JSON job containing job ID, performance,
instrument state, sample rate, musical start/duration, tail, deterministic seed,
and output location. It schedules the whole phrase before starting `scsynth`,
writes to a sibling temporary file, validates the WAV, atomically renames it,
and atomically publishes a version/state/render manifest.

Setup and repeatable command:

```sh
brew install --cask supercollider
uv venv .venv-sc-qualification
uv pip install --python .venv-sc-qualification/bin/python \
  -r tools/qualification/requirements-supercollider.txt
.venv-sc-qualification/bin/python \
  tools/qualification/supercollider_nrt_phrase.py \
  tools/qualification/fixtures/supercollider-phrase.json
```

The fixture deliberately publishes to `/tmp`, not the repository. A different
absolute `output` may be supplied in a copied job file.

## Recorded evidence

Engine/build versions: `scsynth 3.14.1` (tag Version-3.14.1, build 426edf6),
Supriya 26.9b0, NumPy 2.5.2, Python 3.14.6. Two separate Python process runs
completed with return code 0 in 0.155 s and 0.079 s. Both produced byte-exact
WAV SHA-256
`d145179783f1f6c6fcd263be3dc149555cb850747cd06b41b20802fc3478df93`.
Restart/state recall is therefore **bit-exact for this deterministic stock
SynthDef on this pinned host/build**; this is not a blanket promise for random
UGens, plugins, or future engine versions.

The actual WAV was stereo PCM16 at 48,000 Hz, 120,064 frames (2.501333 s), peak
0.195190 and RMS 0.034750. The declared 0.250 s start silence was retained. The
first sample above -80 dBFS was sample 12,033, an observed 33-sample/0.688 ms
offset from the declared event boundary. The final active sample was 91,251;
the third note's release remained active 0.151063 s past the declared 1.750 s
musical end. The remaining declared tail is silence and was not trimmed.

Important API detail discovered during the probe: Supriya's NRT sample rate is
the `Score.render(sample_rate=...)` argument. Setting only
`Options(sample_rate=...)` still rendered at 44.1 kHz. The wrapper passes and
then verifies the NRT argument explicitly.

The generated `/tmp/llm-studio-sc-qualification.wav.json` records job,
instrument-state, SynthDef, and audio hashes plus all measurements. The WAV and
manifest are local evidence and are intentionally not committed.

## Decision and remaining limits

Adopt SuperCollider NRT for the first synthesis worker and use this probe's
contract/publication pattern as the minimum boundary. Reuse the connector's
SynthDef and NRT learnings after giving it a stable source reference; do not
reuse its current `render(template, params, wav, duration_s)` method unchanged.

Before calling this production-ready:

- change intermediates to the specification's 32-bit float WAV (the current
  Supriya evidence path uses PCM16 for simple stdlib inspection);
- add cancellation/deadline/process-group enforcement and resource metrics;
- define validation for overlapping/polyphonic notes, controllers, pitch bend,
  and tempo-derived timing;
- qualify every non-deterministic UGen and third-party UGen separately;
- reconcile the measured 33-sample onset offset at the import boundary without
  double compensation;
- choose and commit a repository licence compatible with dependencies.

This qualifies one known dry synth phrase and Gate B mechanics, not the musical
quality or breadth of the eventual instrument catalogue.
