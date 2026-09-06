# New-agent handoff

Updated: 2026-09-06. Repository: `cotyledonlab/llm-studio`. Branch: `main`.

## Implementation continuation — 2026-09-06

Work progressed on `feat/reaper-studio-bootstrap`. Read
[`docs/qualification/reaper-environment.md`](docs/qualification/reaper-environment.md)
and [`adapters/reaper/README.md`](adapters/reaper/README.md) before resuming.
The earlier assignment below is retained as the original handoff, not a claim
that its implementation is still untouched.

Implemented: pinned controller boundary, safe bootstrap CLI with durable
backups/recovery, exact single-daemon hook, and disposable-only session/GUID,
gain/pan, FX discovery and WAV-import adapter. The full upstream suite passed
47 tests; this slice passed 27 local tests including actual pinned-resource
install/rollback and Lua syntax checks. A real disposable REAPER handler run
passed GUID rename/reorder/deletion/session-switch and durable import checks;
rendered gain/pan measurements passed. Producer project selection was restored
and its state-change count remained unchanged. No live bootstrap was applied.

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
- `main` was clean and synchronized with `origin/main` at handoff creation.
- Ardour issue #8 is closed with a bounded no-go. Its reports are historical pivot evidence, not work to resume.
- SuperCollider issue #12 is closed: the NRT pattern passed a real isolated phrase render. Reuse mechanics/SynthDefs selectively, not the immature connector API unchanged.
- Pedalboard issue #13 is closed: Pedalboard 0.9.24 with Dexed VST3 1.0.1 passed real state restore, MIDI/CC and repeat-render checks. DawDreamer was not needed.
- Gate A is open on REAPER. Gate B still needs the catalogue (#14) and worker isolation/alignment (#15). Gate C and later coordination remain blocked.

## Exact next task

Start GitHub issue #9: **Adopt the REAPER controller and automate studio bootstrap**. Do not start #10 or build the coordinator before #9's real acceptance evidence exists.

The relevant adjacent repository is `/Users/johnmaher/code/reaper-controller`, clean at commit `fd56d0008ffa5fba25cc58a70e5ae632c80b4c16`. Follow its `AGENTS.md`; read `skills/reaper/SKILL.md`, `README.md`, `SPEC.md`, `docs/pitfalls.md` and the ticket reports before changing or invoking it.

At handoff, these read-only checks passed:

```text
REAPER: /Applications/REAPER.app
Version: 7.79.0_06dd787u
Resource directory: present
Headless render flags: present
Bridge queues: present
Bridge daemon: alive
OSC receive/feedback and Web Remote ports: in use
Controller doctor: overall OK
Controller tests: 47 passed in 1.64 s with CoreMIDI/loopback access
REAPER evaluation notice: yes
```

The full suite aborts/fails if the agent sandbox denies CoreMIDI or loopback socket creation; `tests/test_midi.py` and two OSC loopback tests exercise those host facilities. Re-run with the narrow required local-device/network permission before diagnosing a product regression. The same suite passed fully once that permission was granted during this handoff.

John is willing to purchase REAPER. Purchase, account handling and licence activation are producer actions; do not automate or claim them complete. The evaluation notice is not a technical Gate A failure, but the paid prerequisite must remain explicit.

## Issue #9 execution order

1. Create a feature branch/worktree and inspect both repositories without changing John's live project.
2. Pin the controller reuse mechanism and document its licence/interface boundary. Do not casually copy its implementation into this repository.
3. Re-run controller tests with the required CoreMIDI/loopback permission, then `doctor`, `status` and read-only live discovery. Preserve requested-versus-observed evidence.
4. Design bootstrap as plan/dry-run/apply/verify/rollback. It may copy approved scripts, OSC resources and create queues, but must back up every touched REAPER configuration file, preserve unrelated preferences and refuse unsafe changes while REAPER is running.
5. Identify any unavoidable producer action inside REAPER and report it precisely. Do not replace it with mouse, keyboard, Accessibility or screenshot automation.
6. Add the thin LLM Studio adapter and real disposable-project tests required by #9: session identity, stable track GUIDs, durable stem import, mixer/FX readback, rename/reorder/delete/session-switch behaviour and audible gain/pan evidence.
7. Commit and push each logical working state. Update the issue with observed evidence; do not close it on mocks or controller tests alone.

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

cd /Users/johnmaher/code/reaper-controller
git status --short --branch
.venv/bin/python -m pytest
.venv/bin/reaper-connector doctor
.venv/bin/reaper-connector status
```

Run mutation commands only after the safety checks in the controller skill and only against a disposable project. The handoff is complete when the next agent can state which #9 acceptance criteria have real evidence, which remain blocked, and what exact producer action—if any—is required.

## Copy/paste assignment

> Work issue #9 in `cotyledonlab/llm-studio`: adopt the existing `/Users/johnmaher/code/reaper-controller` at pinned commit `fd56d0008ffa5fba25cc58a70e5ae632c80b4c16` and automate safe REAPER studio bootstrap. Read both repositories' instructions and `HANDOFF.md` first. Use a feature branch/worktree, preserve requested-versus-observed evidence, touch only disposable REAPER projects, never use GUI automation, and do not manipulate purchase/licence activation. Implement plan/dry-run/apply/verify/rollback bootstrap plus the thin stable-GUID/mixer/import adapter and real acceptance evidence required by issue #9. Commit and push logical working states; do not start #10 or close #9 on mocks alone.
