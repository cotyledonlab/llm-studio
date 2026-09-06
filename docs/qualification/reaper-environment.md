# REAPER integration qualification — issue #9

Date: 2026-09-06. Status: bootstrap and handler implementation qualified below;
installed studio bridge and producer checks remain open. **Not a Gate A pass**.

## Baseline observed this session

- Studio handoff commit: `00314ad` (initial local checkout clean on `main`).
- External controller: `/Users/johnmaher/code/reaper-controller`, clean at
  `fd56d0008ffa5fba25cc58a70e5ae632c80b4c16`.
- REAPER binary: `/Applications/REAPER.app/Contents/MacOS/REAPER`.
- Version: `7.79.0_06dd787u`; evaluation notice present. Purchase and activation
  remain producer actions and are not claimed complete.
- Controller `doctor`: overall OK; resource directory, default OSC resources,
  render flags and bridge queues present; daemon alive; no orphan requests.
- Controller `status`: daemon alive; OSC receive, feedback and Web Remote
  ports reported occupied. Port occupancy alone does not prove protocol health.
- Existing OSC surface line matches the controller's documented Agent surface
  (`8000`, feedback `127.0.0.1:9000`). Existing bridge action is registered.
- Controller tests excluding native MIDI and socket loopbacks:
  `.venv/bin/python -m pytest -q -p no:cacheprovider --ignore=tests/test_midi.py -k 'not loopback and not capture'`
  → **43 passed, 2 deselected**. This is deliberately not the complete suite.
- Complete controller suite with required host permissions:
  `.venv/bin/python -m pytest -q -p no:cacheprovider`
  → **47 passed in 1.65 seconds**.

No producer project, preferences, installed scripts or plugins were modified
by these checks. File-drop discovery needs permission to write the controller
queue even when the requested REAPER operation is read-only.

Live `hello` returned REAPER `7.79/macOS-arm64`, 16 tracks and state-change
count 70. `studio.session_snapshot` returned `UNKNOWN_OP`, confirming that
the installed bridge does not yet have this extension.

## Integration adjustment

Reuse the controller as an external pinned checkout; do not vendor its generic
bridge. Its current bridge can return a GUID when adding a track, but subsequent
mix operations target indices. It lacks session identity, full GUID discovery
and durable audio import. A narrow studio handler loaded by the existing bridge
is required. Session and GUID checks must execute inside its serialized REAPER
callback; a Python read followed by an index write would not preserve identity
across producer edits.

The extension uses the official [ReaScript API](https://www.reaper.fm/sdk/reascript/reascripthelp.html).
API documentation and simulated tests establish implementation intent; only
observed replies and actual renders qualify this integration.

The controller declares MIT in `pyproject.toml` but has no standalone LICENSE
file at the pin. Private reuse continues through the external checkout. Obtain
the upstream copyright/licence notice and choose the studio's outgoing licence
before distribution. See `adapters/reaper/controller-pin.json`.

## Remaining acceptance evidence

- Real clean-profile installation/startup and OSC round-trip verification.
- Studio extension activation and observed capability/session discovery.
- End-to-end Python adapter → installed controller → REAPER evidence, including
  bridge restart and a nonempty FX chain. Native handler evidence below covers
  the core semantics but is not this full transport chain.
- A producer manually moved fader readback and listening confirmation. Native
  API changes in the harness are not human interaction evidence.

Issue #9 remains open until its real acceptance evidence exists. Issues #10,
#11 and the coordinator remain dependent work. Loading/reloading a ReaScript
may need a precise producer action; do not automate the DAW GUI to bypass it.

## Resume readiness — 2026-09-06

Fetched the existing feature branch; local and remote were aligned with no
local edits. Issue #9 remains open and PR #32 remains draft. The adjacent
controller remains clean at the pinned commit.

Repeated `doctor` and `status`: overall OK, daemon alive, queues present with
zero orphans. Read-only live `hello` returned 16 tracks and state-change count
73; `studio.session_snapshot` again returned `UNKNOWN_OP`. This confirms the
installed studio extension is still the blocker, not a missing controller.
These reads do not establish OSC round-trip health.

Fresh, unapplied bootstrap previews are under
`/private/tmp/llm-studio-reaper/resume-20260906/`:

- `profile-plan.json`: replace the bridge, add the studio handler, retain the
  matching OSC file and existing INI configuration.
- `clean-plan.json`: install bridge, handler, OSC file and INI into the empty
  `clean-profile/` directory. No process-detection override was used.
- `adapter-session.RPP`: upstream `create --template song` fixture with one
  named ReaSynth MIDI track. File readback confirms its content; it has not
  been loaded and does not yet prove nonempty live FX discovery.

The installed binary's command-line usage documents `-cfgfile file.ini` with
an absolute path as an alternate resource directory, plus file/script execution
in argument order. This prepares a supported clean-profile launch path; it is
not yet observed startup evidence. A producer save/quit window was requested
before installation. No live configuration, project or daemon was changed.

The new read-only `reaper_adapter_probe.py` was exercised through the actual
pinned Python controller. It exited 1 with `UnsupportedReaperCapability:
UNKNOWN_OP` and saved failed evidence to `installed-probe.json` in the same
temporary directory. It did not prompt for fader movement or report a pass.
The complete studio suite with `REAPER_CONTROLLER_CHECKOUT` set passed
**35 tests in 0.58 seconds**, including pinned-resource install/rollback and
the new probe's evidence preservation, timeout and session-change checks.
The unchanged upstream suite was not rerun in this resume session.

## Implemented and verified in this slice

The safe bootstrap CLI and adapter are documented in
[`adapters/reaper/README.md`](../../adapters/reaper/README.md).

`REAPER_CONTROLLER_CHECKOUT=/Users/johnmaher/code/reaper-controller
/Users/johnmaher/code/reaper-controller/.venv/bin/python -m pytest -q`
passed **27 tests in 0.56 seconds**. This includes the real pinned-source hook,
Lua syntax checks, installation in a never-launched disposable resource tree,
idempotence, rollback, injected partial-write failure recovery, corrupted
backup refusal, symlink rejection, typed controller errors and readback checks.
The disposable resource tests explicitly provide an inactive-profile process
probe; they do not assert that the producer's REAPER is stopped.

The real profile preview would replace `Scripts/agent_bridge.lua`, add
`Scripts/llm_studio_reaper.lua`, and retain the already matching OSC file and
INI configuration. No live file was changed. Apply with actual permitted
process detection returned `REAPER appears to be running; refusing configuration
writes`. Sandboxed process detection returned unexpected status 3 and also
refused, rather than treating an unknown state as stopped.

The first preview exposed lowercase `[reaper]` in the actual profile; the INI
planner now handles section names case-insensitively without creating a second
section. This has a regression assertion.

## Native handler and audio evidence

The supported `REAPER -nonewinst -noactivate script.lua` command executed the
bounded qualification script, without mouse/keyboard/Accessibility automation.
This interface is documented in the [official v6.80 changelog](https://www.reaper.fm/download-old.php?ver=6x)
and present in the installed 7.79 binary's command-line usage strings.

The completed run is retained locally under
`/private/tmp/llm-studio-reaper/qualification-6sk64bx9/` (WAVs/projects are not
committed). Its `handler-evidence.txt` recorded:

- Stopped producer transport; a new disposable tab with two native track GUIDs.
- Saved project identity and durable one-second audio import, read back from
  the actual item/source, including position and item GUID.
- External native gain edit read back at 0.75; handler gain/pan read back at
  0.5 and hard right. The external edit was programmatic, not a manual fader.
- Rename/reorder preserved the GUID target and its gain. Deletion returned
  `TRACK_ORPHANED`; switching away and back rejected the previous token with
  `SESSION_CHANGED`.
- `producer_project_restored=true` and `producer_state_unchanged=true`.

The adopted controller rendered `baseline.RPP` and `processed.RPP` successfully
to 24-bit stereo WAVs (265,290 bytes each). The committed audio-comparison tool
observed 44,100 frames at 44,100 Hz in both:

| Measurement | Baseline | Half gain, hard right |
|---|---:|---:|
| Left RMS | 0.06443388166 | 0 |
| Right RMS | 0.06443388166 | 0.03221693994 |
| Peak | 0.09156596661 | 0.04578304291 |

Right-channel gain ratio: **0.4999999862**. Both files are non-silent and
unclipped; the requested gain/pan change is present in rendered samples.
This is objective audio evidence, not a claim of producer listening approval.

The first native harness run failed its saved-path assertion and safely restored
the producer project. `Main_SaveProjectEx(..., 0)` saves a copy; the documented
flag `8` establishes the new project filename. Correcting that flag produced
the passing run above. A separate read-only probe also established that
`GetSetProjectInfo_String(..., 'PROJECT_GUID', ...)` returns false in this build:
session identity therefore uses saved path plus a handler nonce and observed
project-pointer epoch. Native track GUIDs remain the track identity.

Disposable tabs from qualification remain available for inspection; producer
tabs were not closed. The installed daemon and live preferences remain intact.
Final live discovery still returned 16 tracks, with state-change count 73
(initial discovery was 70). Each synchronous handler run reported its captured
producer count unchanged; the later count increase is not attributed by this
evidence. Do not interpret those per-run checks as proof that no producer or
host state changed across the entire working session.

## Deferred boundaries

The handler's tick-based session token does not promise detection of a switch
away and back entirely between callbacks. This is not a production write lease.
Producer-owned project writes, automation envelopes and strict conflict semantics
remain disabled/out of scope pending #10. Import retries can duplicate items
after an uncertain transport outcome; do not retry blindly. Licence notices
and outgoing licensing remain a pre-distribution follow-up for #30.
