# REAPER integration qualification

This is a private, macOS qualification slice, restricted to disposable projects.
It does not authorize production mix proposals. Issue #10 envelope work is
under qualification; see the bounded contract below.

The external controller is pinned in `controller-pin.json`. Its file-drop
transport, OSC resources and renderer remain upstream. `controller-studio-hook.patch`
is an exact patch against that commit: it loads `studio_handler.lua` into the
existing daemon, routes bounded `studio.*` operations and observes session
changes during daemon ticks. No generic bridge code is copied into this repo.

The controller's declared MIT licence has no accompanying copyright notice at
this pin. Resolve that and this repository's outgoing licence before distribution.

## Bootstrap from this checkout

Use Python 3.10+ with this repository's `src` on `PYTHONPATH`, or an editable
installation. Bootstrap assets must remain available in this checkout.
Create an empty resource directory first when preparing a clean profile.

```sh
PYTHONPATH=src python3 -m llm_studio bootstrap-plan \
  --resource '/absolute/REAPER/resource' \
  --controller /absolute/reaper-controller \
  --output /absolute/reviewed-plan.json

# Review the reported files/hashes. Stop REAPER before applying.
PYTHONPATH=src python3 -m llm_studio bootstrap-apply \
  /absolute/reviewed-plan.json --receipt /absolute/setup-receipt.json
PYTHONPATH=src python3 -m llm_studio bootstrap-verify /absolute/setup-receipt.json
PYTHONPATH=src python3 -m llm_studio bootstrap-rollback /absolute/setup-receipt.json
```

Plans capture exact file bytes and prior hashes. Apply checks the controller
pin, rejects stale targets and unsafe process detection, and backs up touched
files before changing them. Existing INI sections/preferences are retained.
The backup directory contains `result.json` before the first installed-file
write: after an interrupted apply, pass that receipt to `bootstrap-rollback`.
Rollback checks every backup and refuses to replace later edits. Apply uses
transaction-specific staging paths recorded in its manifest; recovery removes
only staged files whose content still matches the plan. Changed or incomplete
staged files are retained for inspection without blocking a new transaction.
Rollback also uses unique staging paths so a failed restore can be retried. Empty setup
directories and backup evidence are retained; it never recursively deletes them.
Review plan/receipt files as local setup artifacts; do not accept untrusted ones.

File verification does **not** claim that REAPER loaded the new script.
After applying while stopped, start REAPER and run/reload `agent_bridge.lua`.
Its existing action registration can be reused. Native command-line script
execution is supported and qualified for the test harness; persistent startup
action configuration remains optional and unqualified. Clean-profile native
CLI activation and restart passed on 2026-09-08; when forwarding a script,
include the same absolute `-cfgfile` used at launch. Do not automate the DAW GUI.

## Studio boundary

Construct `ReaperStudioAdapter(reaper_connector.bridge.send)` in an environment
using the verified pinned controller checkout. The Python controller remains
external; bootstrap verifies its checkout rather than downloading a floating
package. The studio adapter has these operations:

| Python method | In-REAPER operation | Observation |
|---|---|---|
| `observe_session()` | `studio.session_snapshot` | Saved path identity, loaded-session token, native track GUIDs |
| `read_track(session, guid)` | `studio.get_track_state` | Gain, pan, FX names/parameter counts |
| `set_mixer(session, guid, gain_db=..., pan=...)` | `studio.set_mixer` | Actual gain/pan after the write |
| `import_stem(session, guid, wav)` | `studio.import_stem` | Native item GUID, source path, duration and position |

`silent=True` is explicit zero gain; `gain_db=None` leaves gain unchanged.
Only WAV import is qualified. Python stages a content-addressed session asset;
REAPER attaches it and reads back the actual item. A failed/timeout reply must
not be blindly retried because native item insertion may already have happened.
Retry/reconciliation policy belongs to subsequent durability work.

Session identity is the saved path, not an invented REAPER project GUID.
The token combines a handler-load nonce with observed project pointer/path
changes. It is invalid after a detected switch or handler restart. A switch
away and back entirely between REAPER callbacks is not guaranteed detectable;
these tokens are not production write leases or a #10 conflict guarantee.
Renames/reorders do not change track GUID bindings; missing GUIDs fail closed.
Writes additionally require trim/read automation mode with no global override.

Both layers restrict writes to canonical disposable projects under
`/private/tmp/llm-studio-reaper/` or `~/Music/ReaperConnector/Test Projects/`.
The Lua module checks symlink components using a fixed, quoted, read-only
shell predicate. This is a macOS qualification boundary, not a hardened
multi-user security boundary or a general cross-platform adapter.

## Verification

```sh
python3 -m pytest
REAPER_CONTROLLER_CHECKOUT=/absolute/reaper-controller python3 -m pytest
python3 tools/qualification/reaper_studio.py           # prepare only
python3 tools/qualification/reaper_studio.py --run     # real disposable tab
python3 tools/qualification/reaper_audio_compare.py /path/printed/by/runner
```

For installed-bridge readback, use the pinned controller's Python environment:

```sh
PYTHONPATH=src /absolute/reaper-controller/.venv/bin/python \
  tools/qualification/reaper_adapter_probe.py \
  --controller /absolute/reaper-controller --resource /absolute/REAPER/resource \
  --output /absolute/new-evidence.json
```

This captures one read-only session/mixer/FX observation and refuses to replace
an existing evidence file. `--manual-fader` captures before/after observations
with a terminal pause for the producer, rejecting a changed session/token.
It never declares the acceptance gate passed. Follow the
[remaining acceptance checklist](../../docs/qualification/reaper-producer-checklist.md)
for installed-profile, restart, OSC, import and human listening evidence.

The live runner requires stopped transport, creates a new disposable tab and
restores the original project selection. It leaves its tab/files for inspection.
Render `baseline.RPP` and `processed.RPP` with the upstream controller's
`render --wav` before audio comparison. The native handler test does not deploy
or restart the producer's daemon and does not replace end-to-end installed
bridge qualification. See the [observed report](../../docs/qualification/reaper-environment.md).

## Volume envelope qualification — issue #10

`read_volume_envelope(session, guid, start_sec=..., end_sec=...)` returns a native
volume-envelope GUID, mode, active/armed state, project/track timebase settings,
raw and linear values, dB/silence, shape/tension/selection and bounded points.
Coordinates are **project seconds**. Envelope beat-attachment preferences and
behavior across tempo changes are not yet qualified; this API does not offer
beat-domain editing. Fader scaling is converted by REAPER's own scaling APIs.

`patch_volume_envelope(session, guid, baseline, points)` takes points with
`time_sec` and `gain_db` (or `silent=True`). It replaces the inclusive range with
linear segments. Endpoints must already exist uniquely and retain their gains;
the right endpoint retains its outgoing shape/tension. Outside points and
non-point envelope metadata are checked exactly. Curved-segment subdivision,
automation items, duplicate point times, ranges over 600 seconds, more than
2,048 total points and chunks over 256 KiB are refused. Existing interpolation
is observed; no claim is made that linear interpolation in native fader space
is linear in dB.

The opaque fingerprint references an exact server-side envelope snapshot,
settings and project state-change count. It expires after 30 seconds and is
single-use on apply; only the latest 32 observations are retained. Comparison
and application run synchronously in one bridge callback without yielding.
Any observed project change, even unrelated work, causes conservative conflict.
A new observation requires a new reviewed proposal, not blind retry. Session
switch/restart invalidates receipts under the previously documented token limits.
Writes require stopped transport, an active volume lane, Trim/Read or Read and
no global automation override. Static mixer writes refuse an affected control
with an active lane, points or automation items, and all non-Trim/Read modes.

`undo_volume_patch(session, guid, patch)` is a **compensating envelope restore**,
not global Undo. It checks that no project revision or target state changed,
then restores only the original envelope in a named undo transaction. It refuses
after unrelated edits, restart or session change. The latest patch alone retains
a recovery receipt. Each applied proposal also has a uniquely named native undo
block, but native undo snapshots can predate changes made by other scripts; the
adapter never invokes global Undo. Transport failure after a mutation has an
uncertain outcome: inspect fresh state and do not retry blindly.
