# REAPER integration qualification — issue #9

Updated: 2026-09-08. Status: installed clean-profile bridge, adapter and OSC
qualified below; manual fader readback and producer listening passed.
**Issue #9 acceptance complete; not a full Gate A pass.**

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

## Acceptance evidence outstanding on 2026-09-06 (historical)

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


## Installed-profile qualification — 2026-09-08

The producer confirmed REAPER was closed. Host process detection confirmed
no running REAPER; sandboxed `pgrep` could not inspect processes and was not
interpreted as a stopped result. Fresh plans were generated and reviewed.
The branch was clean and aligned with origin before this qualification.

Evidence root: `/private/tmp/llm-studio-reaper/qualification-20260908/`.
Generated audio, projects, plans and receipts remain local.

- Clean profile: `clean-profile/`; first apply installed bridge, handler, OSC
  and INI, with a durable receipt. File/queue verification passed. Fresh-plan
  repeat apply reported `changed: []`.
- Normal profile: installed the bridge and studio handler, retained the matching
  OSC file, and did not edit the INI. File/queue verification passed. Recovery
  receipt is `profile-receipt.json`; its backup is
  `~/Library/Application Support/REAPER/LLMStudioBackups/bootstrap-af5892127fad44a4a01e7a19c713ebf4/`.
  Normal-profile runtime activation is not claimed by the clean-profile test.
- Native launch used the absolute `-cfgfile clean-profile/reaper.ini`,
  `-newinst`, disposable `adapter-session.RPP`, then the installed bridge script.
  An initial 5-second probe timed out; the bridge subsequently became active.
  The producer has not identified any startup prompt, so its cause is unknown.
- The installed Python adapter then discovered the exact saved disposable path,
  GUID `{B241E427-5B68-480D-AA41-6CC0F28DA872}`, unity/centre mixer state,
  and `VSTi: ReaSynth (Cockos)` with 18 parameters (`active-snapshot.json`).
- A native read-only script independently confirmed the exact resource path,
  disposable project path and `play_state=0` before mixer/import work.
- Python adapter gain/pan writes returned volume `0.5`, pan `1`; a separate
  read agreed. Restore returned unity/centre and a separate read agreed.
- Added disposable `StudioImport` track, discovered its native GUID, and used
  the Python adapter to stage/import a generated one-second WAV at 4 seconds.
  The installed handler returned the content-addressed source path, item GUID,
  position and length. Details are retained in `installed-checks.jsonl`.
- OSC listener was bound before `/play`. In a bounded three-second run it
  captured 136 events, advancing timecode, track-1 VU maximum `0.8273620605`,
  `/play [1]`, then `/stop [1]` and `/play [0]`. See `osc-evidence.json`.
- Bridge shutdown acknowledged `stopping: true`. After its heartbeat was stale
  for over 24 seconds, the installed script restarted via native CLI. New
  snapshot token differed; `ping` and `hello` passed, and a read using the old
  token returned `SESSION_CHANGED`. See `restart-evidence.json` and
  `restarted-snapshot.json`.

A command-line targeting pitfall was observed: omitting `-cfgfile` from
`-nonewinst -noactivate script.lua` launched a separate normal-profile process.
The read-only script included a resource assertion; no observation file was
produced, so its execution in that extra process is not established. The agent terminated only that newly launched
process (PID 69022). Retrying with the explicit clean-profile `-cfgfile`
forwarded successfully to the original test instance (PID 68814). Process
inspection confirmed it was the only REAPER instance before OSC playback.
The acceptance checklist now includes the required flag. Do not interpret
this as producer-project mutation evidence or an unchanged-preferences claim
for the accidentally launched application's own startup behavior.

All live mutations in the successful checks targeted the disposable project.
At this stage manual fader/listening evidence was pending. Both were later
completed below; no #10 work was started.


The optional fresh render comparison did not pass: after saving two controlled
project copies through native CLI (with actual mixer changes through the Python
adapter) and restoring both tracks to unity/centre, the upstream controller's
`render_project(..., timeout=45)` timed out on `baseline.rendercopy.rpp` without
a WAV. Python reaped that renderer; host process inspection again showed only
PID 68814. `render-mixer-evidence.json` records the observed changes/restores.
The prior native-handler measurements are retained as historical evidence;
no fresh rendered-audio success is claimed. Subsequent live listening
acceptance is recorded below; export reproducibility remains a #11 follow-up.


## Producer manual fader readback — 2026-09-08

The producer first moved MASTER to a displayed -5.99 dB. The track adapter
correctly continued to report both tracks at unity; an independent read-only
native check found MASTER at -5.9921850013755 dB with transport stopped.
This was distinguished from the required track-fader check.

The producer then explicitly reported moving `StudioQualification` to -5.99 dB.
At `2026-09-08T06:03:17.428194Z`, the installed Python adapter returned linear
gain `0.5016383722284`, or **-5.992185001375451 dB**, correctly rounding to
**-5.99 dB**. The native track GUID and post-restart session token matched the
preceding unity observation; pan remained centre and `StudioImport` remained
unity. See local `manual-track-after.json` and `manual-fader-evidence.json`.

**Manual track-fader readback passed.** The producer's changes were retained.
The following live audition completed the remaining human listening check.


## Producer listening and issue #9 acceptance — 2026-09-08

Monitoring: the producer's **laptop speakers**. The installed Python adapter
and OSC lane played two bounded passes of the same disposable MIDI phrase:

- A: producer's existing gain `0.5016383722284` (-5.992185 dB), centre pan.
- B: gain `0.2508191861142` (6.0206 dB quieter), hard-right pan `1`.

The first audition was not accepted; the producer requested a retry. The retry
used a three-second pause between passes. It captured 104 OSC events for A
and 112 for B, including stop feedback in both. The adapter observed the
requested change, then restored the exact producer gain and centre pan.
After being asked whether both passes were heard and the second was quieter
or shifted right, the producer confirmed: **"yes that went as expected"**.
This is basic listening acceptance on laptop speakers, not a calibrated
stereo-monitoring or musical-quality evaluation.

A final independent read at `2026-09-08T06:07:49.431594Z` retained the same
session token and native GUID and confirmed -5.992185001375451 dB, pan 0.
The producer's MASTER adjustment was not changed by either audition.
Local artifacts: `listening-evidence.json` (first attempt),
`listening-retry-evidence.json`, `producer-listening-confirmation.json`, and
`accepted-final-snapshot.json`. Raw capture deliberately does not self-certify
human listening; the separate producer confirmation supplies that evidence.

All five issue #9 acceptance criteria now have evidence: clean bootstrap and
installed bridge/OSC; idempotence/backups/safe refusal; native GUID behavior;
manual fader and audible programmatic mixer changes; reproducible pinned
controller boundary. PR #32 can leave draft for review and merge. Keep #9
open until its implementation is merged; this is not completion of Gate A.
#10 automation/conflict semantics and #11 replacement/save/reopen/export remain
subsequent work. The fresh optional render timeout is still unresolved and
must be reproduced before claiming reliable export; previous successful native
renders and this live audition do not erase that failure.


## Pre-merge review and recovery correction — 2026-09-08

Two independent Luna subagents reviewed standards and issue #9 conformance
against base `00314ad` and implementation head `9c09113`. Neither found a
separate standards violation or out-of-scope/missing #9 behavior. Both identified
a blocking recovery defect: failed file replacement left a deterministic stage
filename behind, so rollback followed by a new apply could refuse indefinitely.
An analogous failed rollback replacement could block retrying rollback.

The correction records a unique staging path per apply transaction, cleans
matching staged content after a synchronous failure or rollback, and uses
unique restore stages for rollback. Edited/incomplete staging files are kept
for inspection rather than deleted, and do not block new transactions. Existing
recovery receipts remain readable without the optional staging metadata.

Regression coverage now verifies synchronous failure cleanup, simulated
interruption cleanup, preservation of changed staged content and unrelated
files, re-apply after rollback, and retry after a failed rollback replacement.
The full studio suite with the actual pinned controller passed **37 tests in
0.90 seconds**; diff whitespace checks passed. This changed local bootstrap
recovery only; the installed bridge/handler and live producer mix were not
modified during review. The live acceptance evidence above remains applicable.
