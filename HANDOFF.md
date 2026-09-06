# New-agent handoff

Updated: 2026-09-06. Repository: `cotyledonlab/llm-studio`.
Resume branch: `feat/reaper-studio-bootstrap`.
Draft PR: [#32](https://github.com/cotyledonlab/llm-studio/pull/32).

## Resume preparation — 2026-09-06

Fetched and confirmed the existing branch is aligned with origin; #9 is open
and #32 is still draft. Read-only readiness again passed. Live `hello` returned
16 tracks/count 73; studio discovery still returns `UNKNOWN_OP`. Do not merge
the PR merely to deploy for qualification: test from this feature branch first.

Fresh **unapplied** current-profile and clean-profile plans, plus an upstream
ReaSynth project fixture, are at
`/private/tmp/llm-studio-reaper/resume-20260906/`. Details are in the qualification
report. The producer was asked to save and quit REAPER before installation;
no stopped-window confirmation has been received at this point. Do not infer
confirmation from elapsed time. Recheck readiness and regenerate stale plans
before applying. No live project/configuration/daemon mutation occurred.

Two Luna subagents prepared a read-only installed-adapter evidence probe and
[producer acceptance checklist](docs/qualification/reaper-producer-checklist.md).
The probe is for observing installed capability and collecting fader evidence;
it cannot substitute for the remaining real import/mixer/OSC/restart checks or
producer listening. Use the checklist to continue the same #9 gate, not #10.

Validation of this preparation: 35 studio tests passed with the actual pinned
checkout enabled. The new probe's real installed-bridge run recorded
`UnsupportedReaperCapability: UNKNOWN_OP` in local `installed-probe.json`.
The default probe is noninteractive; `--manual-fader` adds a terminal pause.

## Implementation continuation — 2026-09-06

Work progressed on `feat/reaper-studio-bootstrap`. Read
[`docs/qualification/reaper-environment.md`](docs/qualification/reaper-environment.md)
and [`adapters/reaper/README.md`](adapters/reaper/README.md) before resuming.
Implementation commits are `a390836` (pin/baseline), `61cd637` (bootstrap),
and `074b093` (adapter/qualification). They are committed and pushed; PR #32
is open and draft, not merged. This handoff update follows those commits.

Implemented: pinned controller boundary, safe bootstrap CLI with durable
backups/recovery, exact single-daemon hook, and disposable-only session/GUID,
gain/pan, FX discovery and WAV-import adapter. The full upstream suite passed
47 tests; this slice passed 27 local tests including actual pinned-resource
install/rollback and Lua syntax checks. A real disposable REAPER handler run
passed GUID rename/reorder/deletion/session-switch and durable import checks;
rendered gain/pan measurements passed. Each synchronous handler run restored
producer project selection and reported its captured state-change count
unchanged. Final discovery had 16 tracks and count 73 versus initial count 70;
the later increase is unattributed, so do not claim the entire working session
had unchanged state. No live bootstrap was applied.

**Next:** finish #9's installed-profile/bridge-restart/OSC and end-to-end adapter
qualification in a suitable stopped-profile window; obtain actual manual-fader
and listening evidence. Live bootstrap correctly refuses while REAPER runs.
Do not close #9 or start #10 from unit/native-handler tests alone. Two Terra
agents produced the initial work but hit their usage limit; the primary agent
completed review, fixes, integration and native qualification.

## Mission

Build the smallest producer-led workflow in which agents create and revise musical takes while John retains authoritative manual control of the accepted REAPER project. Use background APIs, scripts and file protocols only; never automate the DAW GUI.

## Current position

- Architecture pivoted from Ardour to REAPER in commit `a7827d7`; read [the ADR](docs/adr/0001-reaper-as-authoritative-daw.md), [domain language](CONTEXT.md), [specification](SPEC.md) and [implementation plan](docs/IMPLEMENTATION_PLAN.md).
- The implementation is on the pushed feature branch and draft PR #32; do not
  start again from `main` or duplicate this work. Check for new remote changes
  and local edits before resuming.
- Ardour issue #8 is closed with a bounded no-go. Its reports are historical pivot evidence, not work to resume.
- SuperCollider issue #12 is closed: the NRT pattern passed a real isolated phrase render. Reuse mechanics/SynthDefs selectively, not the immature connector API unchanged.
- Pedalboard issue #13 is closed: Pedalboard 0.9.24 with Dexed VST3 1.0.1 passed real state restore, MIDI/CC and repeat-render checks. DawDreamer was not needed.
- Gate A is open on REAPER. Gate B still needs the catalogue (#14) and worker isolation/alignment (#15). Gate C and later coordination remain blocked.

## Exact next task

Finish GitHub issue #9: **Adopt the REAPER controller and automate studio bootstrap**.
Its implementation checklist is updated, but the issue remains open. Epic #1
has a progress comment; issue #30 records the licence-notice follow-up.
Do not start #10 or build the coordinator before #9's real acceptance evidence exists.

The relevant adjacent repository is `/Users/johnmaher/code/reaper-controller`, clean at commit `fd56d0008ffa5fba25cc58a70e5ae632c80b4c16`. Follow its `AGENTS.md`; read `skills/reaper/SKILL.md`, `README.md`, `SPEC.md`, `docs/pitfalls.md` and the ticket reports before changing or invoking it.

During the completed implementation session, these checks passed (re-observe
live readiness before new DAW work):

```text
REAPER: /Applications/REAPER.app
Version: 7.79.0_06dd787u
Resource directory: present
Headless render flags: present
Bridge queues: present
Bridge daemon: alive
OSC receive/feedback and Web Remote ports: in use
Controller doctor: overall OK
Controller tests: 47 passed in 1.65 s with CoreMIDI/loopback access
Studio tests: 27 passed, including real pinned-source install/rollback
REAPER evaluation notice: yes
```

The full suite aborts/fails if the agent sandbox denies CoreMIDI or loopback socket creation; `tests/test_midi.py` and two OSC loopback tests exercise those host facilities. Re-run with the narrow required local-device/network permission before diagnosing a product regression. The same suite passed fully once that permission was granted during this handoff.

John is willing to purchase REAPER. Purchase, account handling and licence activation are producer actions; do not automate or claim them complete. The evaluation notice is not a technical Gate A failure, but the paid prerequisite must remain explicit.

## Issue #9 execution order

1. Resume the feature branch; read the qualification report, adapter README and
   controller instructions. Inspect PR #32 and issue #9 for newer changes.
2. Re-observe live readiness without mutating the producer project. The installed
   original daemon answered `hello` but rejected `studio.session_snapshot` with
   `UNKNOWN_OP`; the studio extension has not been deployed there.
3. Complete clean-profile installation, OSC round-trip and bridge-restart
   qualification. Use a genuinely safe stopped-profile window. Do not stop the
   producer's application or bypass the installer's running-process refusal
   merely to finish the gate. Regenerate and review a fresh bootstrap plan;
   prior local plans are snapshots and may be stale.
4. Prove the full Python adapter → installed controller → REAPER chain,
   including nonempty FX discovery. The native handler test already proved
   core semantics but did not exercise the installed extension/transport chain.
5. Obtain actual producer fader movement/readback and listening evidence. A
   native API edit is not a human fader test. Bundle any unavoidable producer
   actions into a precise handoff after independent preparation is complete.
6. Commit/push working states and update #9/#32. Keep #9 open until all its
   acceptance evidence exists; do not merge or close from mock tests alone.

## Evidence and implementation map

- `src/llm_studio/bootstrap.py` and `__main__.py`: plan/apply/verify/rollback;
  an interrupted apply has a recovery receipt in its backup directory.
- `src/llm_studio/reaper.py`: dB/silence boundary, typed failures, native GUID
  targeting, content-addressed WAV staging and observed import readback.
- `adapters/reaper/controller-studio-hook.patch` and `studio_handler.lua`:
  bounded extension of the pinned daemon, not a second bridge. Saved project
  path is session identity; the assumed `PROJECT_GUID` API was unsupported.
- `tools/qualification/reaper_studio.py` / `.lua`: prepare/run a disposable
  native handler test using supported CLI script execution; restore original
  project selection and retain scratch tabs for inspection.
- `tools/qualification/reaper_audio_compare.py`: checks rendered half-gain and
  hard-right pan. Observed right RMS ratio was `0.4999999862`, left RMS zero.
- Passing local runtime evidence lives at
  `/private/tmp/llm-studio-reaper/qualification-6sk64bx9/`. These temporary WAVs,
  projects and raw evidence are intentionally not committed and may expire.
  The durable report and reproducible harness are committed.

Writes are deliberately disposable-only. Callback-observed session tokens are
not production conflict/write leases; a switch away and back wholly between
callbacks is not guaranteed detectable. WAV import outcomes must not be retried
blindly after a timeout. Keep these limits visible for #10 and later durability
work. The controller declares MIT but lacks a standalone copyright/licence
notice; resolve before distribution under #30, not by copying its implementation.

## Safety and authority boundaries

- Treat the open REAPER project as producer-owned. Use only disposable projects under the controller's documented test/scratch paths unless John explicitly names a real project.
- Only one agent/process may mutate the live REAPER session. Background renderers must not acquire its audio device.
- Requested is not observed. Read back every mutation and preserve operation/session identity.
- Do not edit REAPER preferences while REAPER is running unless the exact operation is already qualified as safe.
- Never install plugins during a take. Future plugin acquisition is governed catalogue provisioning under #31: approved pinned source, hashes/signatures, licence/provenance, explicit installation approval, qualification and rollback.
- Do not commit plugin binaries, sample libraries, private audio, credentials or generated qualification WAVs.

## Known gaps after #9

- #10 must add bounded REAPER envelope read/write, mode/shape/time-base fidelity, atomic stale-state rejection or explicit producer handoff, and safe undo.
- #11 must prove mix-preserving take replacement, binding recovery, save/reopen and final export.
- #14 must qualify the actual drum, bass and keys catalogue; a plugin being installed or listed is not sufficient.
- #15 must add cancellation, deadlines, process-group isolation, resource measurement and alignment without affecting REAPER.
- #31 is P2 post-v1 convenience, not permission to build a plugin marketplace now.

## Useful commands

```sh
cd /Users/johnmaher/code/llm-studio
git status --short --branch
gh issue view 9
gh pr view 32
REAPER_CONTROLLER_CHECKOUT=/Users/johnmaher/code/reaper-controller \
  /Users/johnmaher/code/reaper-controller/.venv/bin/python -m pytest -q

cd /Users/johnmaher/code/reaper-controller
git status --short --branch
.venv/bin/python -m pytest
.venv/bin/reaper-connector doctor
.venv/bin/reaper-connector status
```

Run mutation commands only after the safety checks in the controller skill and only against a disposable project. The handoff is complete when the next agent can state which #9 acceptance criteria have real evidence, which remain blocked, and what exact producer action—if any—is required.

## Copy/paste assignment

> Resume issue #9 and draft PR #32 in `cotyledonlab/llm-studio` on `feat/reaper-studio-bootstrap`. Read `HANDOFF.md`, the qualification report, adapter README and adjacent controller instructions first. Bootstrap and the disposable-session adapter are already implemented and pushed, with 27 studio tests, 47 controller tests and real native handler/render evidence. Finish installed clean-profile/OSC/bridge-restart and full Python-to-bridge qualification, then actual producer-fader/listening acceptance. Preserve the producer project; never bypass the running-process guard or automate the DAW GUI. Pin deferred work in GitHub, involve John only for real blockers/unavoidable actions, and commit/push progress. Do not restart implementation from main, merge/close #9 prematurely, or begin #10.
