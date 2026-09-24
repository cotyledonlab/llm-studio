# REAPER Gate A / issue #11 qualification

Updated: 2026-09-23. **The installed A4 replacement, save/reopen, and export
passed on a disposable copy; Gate A is not yet accepted.** The human Bass move
was observed and preserved. Bridge owner recovery passed in a separate
disposable profile; wider Gate A coverage remains open. This report does not
replace the completed [A3 automation
qualification](reaper-automation.md) or claim the old renderer timeout is fixed.

## Scope and builds

Host: REAPER `7.80/macOS-arm64` on macOS 26.5.2. Controller protocol remains
pinned at `fd56d0008ffa5fba25cc58a70e5ae632c80b4c16`; the adjacent
checkout currently includes one later instruction-only commit. The first A4
native run loaded this branch's `studio_handler.lua` directly inside a REAPER
ReaScript. The installed file-drop transport was qualified in a later disposable
run described below. All project writes were to disposable copies.

Native evidence (temporary):
`/private/tmp/llm-studio-reaper/gate-a4-693qi2_4/native-evidence.txt` and
`session.RPP`. The copy has Keys, Bass and Drums tracks, three five-second WAV
items, Bass ReaEQ, and a copied volume envelope. The source tab was
`/private/tmp/llm-studio-reaper/a3-probe/session.RPP`. The producer's latest
in-memory Keys envelope differed from its last saved RPP at the two-second
point; the copy captured the in-memory lane exactly. The source RPP on disk was
not modified. The source tab remained dirty, so no claim that its unsaved state
was committed to disk is made.

## Take replacement and reopen

The adapter stages a content-hashed session WAV, then sends the item GUID,
take GUID, source path, duration, format, and project revision back as an
expected native observation. The handler checks these in the same callback as
the source replacement, requires a stopped disposable project and same-length
WAV, and rejects stale or mismatched requests. It retains the item/take and
track GUIDs, reads the source back, and reports uncertainty rather than
blindly retrying a failed write. Unit and injected native-host tests cover
stale observations, format refusal and failed-readback recovery.

On the real disposable copy, the native handler replaced the Drums 330 Hz
source with a 440 Hz source. Reusing the stale observation returned `CONFLICT`.
Keys and Bass track chunks were byte-identical before/after replacement;
John's Keys envelope chunk was also identical. Bass gain `0.50118723362727`,
pan `-0.2`, and `VST: ReaEQ (Cockos)` survived save/reopen. The first reopen
readback checked track names and media paths, but did not compare every
pre-save track/item/take GUID to its reopened binding. Independent review
identified that gap. The corrected native run at
`/private/tmp/llm-studio-reaper/gate-a4-7rng30qk/native-evidence.txt` records
and compares all three GUIDs per part across save/reopen; each comparison
passed. This Bass gain was set by the test script; it is **not** counted as a
new human fader observation.

Opening the saved project ended the running ReaScript before its subsequent
lines. A separate readback script completed reopen verification and restored
the original tab. The first sandboxed CLI forwarder aborted during macOS app
registration before it wrote a native report; the existing REAPER process
survived. The corrected elevated forwarder reached the copy. These failed
attempts are not acceptance passes. The first successful run did not record an
in-memory source revision baseline; its saved source RPP bytes were checked
separately. Later runner revisions record the source revision and dirty flag
across both scripts.

## Export and audio measurements

The explicit-profile, 30-second-bounded `-renderproject` path rendered the
reopened copy in 1.843 seconds: stereo 24-bit PCM, 44.1 kHz, 220,500 frames,
five seconds. Evidence:
`/private/tmp/llm-studio-reaper/gate-a4-export-rgwcznsd/export-evidence.json`.
The old no-profile controller command, tried once on the same copied fixture
with a 15-second bound, also completed in 1.983 seconds. The September 45-second
timeout is therefore **not reproduced or explained**; the prior failure is
retained as a reliability limitation rather than erased.

On 2026-09-24, the controller call was rerun with process, stdout, stderr,
elapsed time, and output hash captured. `reaper_connector.audio.render_project`
has no profile parameter; it invokes `[BIN_PATH, "-renderproject", target]`
without `-cfgfile`. Against a copied five-second A4 RPP with a 45-second
timeout, this exact library path exited 0 in 1.914 seconds and produced a
1,323,690-byte WAV (SHA256
`f324d3d307458d88eeaf020bf1f9aa972fffae5a48763f4b76c52185f88ef3e1`).
The only stderr was REAPER's Metal device initialization message. The captured
run evidence is `/private/tmp/llm-studio-reaper/renderer-timeout-rerun-20260924/controller-call-evidence.json`.

A preceding sandboxed default-profile launch aborted in 0.125 seconds while
macOS registered the REAPER process; its crash report identifies
`___RegisterApplication_block_invoke`, and it wrote no WAV. A run of the same
fixture with a newly created disposable profile and a 30-second bound exited 0
in 18.977 seconds. These controlled runs did not reproduce the historical
45-second timeout. The immediate sandbox-specific abort and slower first run
with a fresh profile do not explain the historical failure, whose exact input
and process output were not retained. Keep the timeout unresolved. Further
controller probes can set an explicit profile only by wrapping or changing the
controller's process invocation.

Three isolated RPP copies, each muting the other two tracks, rendered aligned
Keys, Bass and Drums exports. All had the same sample rate and 220,500-frame
bounds. Their sum differed from the stereo mix by at most one 24-bit sample
unit (`RMS ratio 1.20e-6`). In the Keys stem, RMS at 2.4–2.6 seconds was
194.85 sample units versus 219,019.58 early and 249,806.71 late, showing
the copied envelope is audible. Bass left/right RMS was 208,665/166,932,
consistent with its negative pan. The Drums stem contained a strong 440 Hz
component and negligible 330 Hz component. Evidence:
`/private/tmp/llm-studio-reaper/gate-a4-stems-yq1lv7j2/audio-evidence.json`.
These are deterministic test tones, not a musical-quality judgement. Part
exports came from controlled offline RPP copies, not REAPER's native stem
batch mode.
The export checker now derives the five-second full-project bound from the
fixture's item positions and lengths. A read-only recheck of the retained mix
and all three stems found 220,500 frames each at 44.1 kHz. This is a zero-extra-
tail fixture; it does not qualify tails from instruments or effects in other
projects.

## 2026-09-23 live continuation

A read-only tab probe found four tabs in the existing `a3-probe` profile,
including three dirty tabs and two tabs sharing the same A4 project path. The
original one-track source tab was closed. A uniquely named disposable copy of
the saved, clean A4 RPP was opened as a fifth tab without closing or saving the
others. Bridge readback recorded its Bass gain, pan and ReaEQ plus the earlier
manual Keys envelope before asking John to move Bass. No changed Bass value or
producer confirmation has been observed yet. This copy does not recover the
later `a3-probe` in-memory Keys edit.

The pinned bridge, studio handler, OSC file and INI were installed in a new,
empty disposable resource under
`/private/tmp/llm-studio-reaper/issue11-installed-prep-20260923/` using the
reviewed isolated-profile bootstrap guard. The existing REAPER PID was
independently identified with a different cfgfile; installation and file-hash
verification passed before starting the second instance. The second instance
opened a separate saved A4 copy, but the installed daemon produced no heartbeat
or file-drop reply. A minimal deferred-callback probe also failed to run its
callback despite executing its top-level code. A blocking startup dialog is a
possibility, not a diagnosis. Installed replacement transport and its live
readback remained unqualified at that point. John subsequently licensed the
isolated instance and its deferred callbacks and bridge heartbeat began
running. The credential is not stored in this repository or qualification
evidence.

John then moved Bass in the uniquely named original-profile handoff tab from
linear gain `0.50118723362727` to near zero, and confirmed that this was the
manual fader move. Bridge readback recorded the change with pan `-0.2`, ReaEQ,
track GUIDs, and Keys points unchanged. A guarded native save of only that
disposable tab wrote `VOLPAN 0 -0.2` to
`/private/tmp/llm-studio-reaper/gate-a4-bass-handoff-5duxo9g9/session-bass-handoff.RPP`
(SHA256 `faf7cf49e91af503015f00086437804e50f78ef89dc18582e0e67b23ef91b6f6`).
The tab itself still reported dirty after `Main_SaveProjectEx`; its saved file
was read independently. The four earlier original-profile tabs were not saved
or closed. This copied fixture contains the earlier Keys point at two seconds,
`0.0419846`, not the later saved `a3-probe` value `1.95447444`.

The isolated instance opened a byte-identical copy of that saved manual RPP in
one unique, clean tab. A native prewrite enumeration showed exactly three tabs,
only one selected target path, stopped transport, and unchanged earlier tab
handles/revisions. The guarded installed adapter made exactly one Drums
replacement request after checking the saved project hash, silent Bass,
track/item bindings, and the original Drums media hash. The installed handler
returned the expected new hash-addressed 440 Hz source and preserved Drums
item/take GUIDs and geometry. Its immediate independent read failed the strict
session-token check. Read-only snapshots then alternated between two token
nonces for the same project and revision, although the OS showed one process
with that resource. This proves duplicate bridge handlers inside the instance;
file-drop requests can race. No replacement retry was made. Evidence:
`/private/tmp/llm-studio-reaper/issue11-installed-human-7y171ubg/installed-a4-evidence.json`.

A one-shot native readback independently found the new Drums source in the
unique selected target tab, the same track/item/take GUIDs and five-second
geometry, exact Bass gain zero with pan and ReaEQ intact, and the older isolated
tabs unchanged. Evidence:
`/private/tmp/llm-studio-reaper/issue11-installed-human-7y171ubg/native-reconcile.txt`.
The target tab was dirty; its saved RPP still references the old Drums source.
A guarded native save attempt stopped before writing on a revision assertion,
and the next forwarded script has not produced a report. Save/reopen and export
of this accepted live replacement therefore remain pending. The duplicate
handler fault also keeps installed transport qualification open despite the
accepted replacement receipt and native post-state.

An explicitly labeled offline RPP copy combined the saved manual handoff bytes
with only the new Drums source path independently seen in native readback. Its
headless render and three isolated part renders passed the silent-Bass export
check: 220,500 aligned frames at 44.1 kHz, zero Bass samples, audible Keys
automation, a strong 440 Hz Drums component, and at most one 24-bit sample of
mix-versus-stem error. Evidence:
`/private/tmp/llm-studio-reaper/issue11-manual-export-_5e43jyr/offline-export-evidence.json`
and `/private/tmp/llm-studio-reaper/gate-a4-stems-39pu0q2d/audio-evidence.json`.
This checks the audio represented by the observed post-state; it is not a
save/reopen or installed transport acceptance pass.

The reviewed bridge patch now reserves a process-local owner generation before
its first deferred tick and checks that generation before each scan. A mocked
Lua host showed an old loop becoming inert after stale-owner takeover; the
pinned-controller suite passed 116 tests with 8 skips. A new licensed disposable
profile under `/private/tmp/llm-studio-reaper/issue11-owner-4yhg_yj8/` was
installed from the pinned plan and its four file hashes verified. Native
preflight found a clean three-track manual-copy tab and stopped transport.
Its bridge still has no heartbeat because even a minimal deferred callback has
not run after script top-level execution. A startup dialog is again suspected;
John was asked to check the new instance. The single-owner runtime behavior
and a complete replacement/save/reopen/export sequence remain unqualified.

John selected an audio device in that new instance; no license dialog appeared
because the protected license file had already been copied into its resource.
The minimal deferred probe then completed and the bridge heartbeat appeared.
Four file-drop snapshots initially showed one stable session token, but the
startup tab unexpectedly contained six in-memory tracks. It was left clean and
untouched. A uniquely named byte-identical copy of the saved manual RPP was
opened in a new tab; native enumeration proved exactly one selected target,
three clean tracks, stopped transport, and the earlier six-track tab unchanged.
Four further snapshots kept one token with the expected three track GUIDs.
Evidence: `/private/tmp/llm-studio-reaper/issue11-owner-4yhg_yj8/tab-proof-before-restart.txt`.

An intentional second launch of the same bridge ReaScript stopped its replies.
Native ExtState inspection found a stale heartbeat after the launch, consistent
with REAPER terminating the old script before the new invocation returned on
the fresh-heartbeat guard. After the heartbeat aged, one launch restored a
single stable bridge token. This lifecycle fault is separate from the earlier
duplicate-handler race. The installed operation below ran with that restored
owner. A later patch removed the fresh-heartbeat startup gate and added
conditional exit cleanup; its separate live qualification is recorded below.

The fresh three-track tab then passed one guarded installed
`studio.replace_stem` call. The handler accepted the same-length 440 Hz Drums
media while transport was stopped. An independent file-drop read with the same
session token confirmed the new hash-addressed source, unchanged item/take
GUIDs and geometry, exact silent Bass gain/pan/ReaEQ, and unchanged Keys
envelope. Evidence:
`/private/tmp/llm-studio-reaper/issue11-owner-4yhg_yj8/installed-a4-evidence.json`
(`ok: true`, `replace_call_count: 1`). A guarded native script saved only that
unique target tab. Its disk RPP SHA256 became
`90c44753ee58367f36f90418f968f9bebc9fa393b1876150745b886696a3cc44`
and records Bass `VOLPAN 0 -0.2`, the Keys point at two seconds `0.0419846`,
and the accepted Drums media path. The tab still reported dirty after
`Main_SaveProjectEx`; no claim that REAPER marked it clean is made.

A byte-identical saved RPP was opened in a new tab. Native readback proved all
three track/item/take GUIDs, each five-second item, the accepted Drums source,
silent Bass with ReaEQ and pan, and the Keys lane. The reopened tab was clean;
both earlier isolated tabs retained their prior dirty states. Evidence:
`/private/tmp/llm-studio-reaper/issue11-owner-4yhg_yj8/reopen-proof.txt`.
Headless rendering directly from this saved and reopened RPP produced a stereo
mix and three aligned part exports: 220,500 frames at 44.1 kHz, zero Bass
samples, audible Keys automation (early/mid/late RMS 219,019.58/4,954.10/
249,806.71), a strong 440 Hz Drums component, and at most one 24-bit sample
of mix/stem error (RMS ratio `7.21e-7`). Evidence:
`/private/tmp/llm-studio-reaper/issue11-live-saved-export-6m79wokj/mix-evidence.json`
and `/private/tmp/llm-studio-reaper/gate-a4-stems-nye0xhlr/audio-evidence.json`.
This is a deterministic signal check, not a human listening judgement. The
fixture configures no extra tail, so it does not qualify nonzero FX tails.

The relaunch-safe bridge patch was installed from the clean pinned controller
in a third disposable profile at
`/private/tmp/llm-studio-reaper/issue11-rerun-0hhcwsdj/`. All four installed
file hashes verified; the protected license was copied without exposing its
contents. Launching REAPER without a project argument avoided the earlier
startup duplication. The deferred probe passed, a three-track saved manual
copy opened in a new tab, and the first installed bridge launch returned three
snapshots with one stable token. A second same-path CLI invocation stopped
replies. Native readback found deferred callbacks running, owner ExtState
cleared, and its heartbeat aged by exit cleanup. A third same-path invocation
started a new owner immediately with four stable snapshots, without waiting
for heartbeat expiry. This is consistent with the REAPER action toggling a
running ReaScript off on the second invocation; the action semantics are an
inference from observed state.

A byte-identical installed bridge script at a distinct filename was then
launched while the prior owner was active. Five file-drop snapshots showed a
new stable session token, with the same three tracks and no project change.
This exercises native owner-generation takeover between distinct script
identities. An explicit `bridge.shutdown` returned success; native readback
found no owner, an aged ExtState heartbeat, running deferred callbacks, and an
unchanged stopped project. One launch of the installed bridge then restored a
new stable token across three snapshots. The on-disk heartbeat may appear
fresh briefly after shutdown because cleanup only ages ExtState. This live
test does not coordinate separate REAPER processes sharing one resource; the
guarded profiles used distinct resources.

## Gate A capability matrix

Statuses refer to the stated evidence scope; copy-based qualification does not
by itself establish the complete producer workflow.

| SPEC ID | Capability | Status and evidence |
|---|---|---|
| A01 | Complete Gate A DAW workflow through APIs/protocols without GUI automation | **Partial.** John clarified on 2026-09-24 that A01 covers the complete Gate A DAW workflow while another application has keyboard focus; the eight-bar musical tracer remains Gate C. Existing A3/A4 work used native APIs, ReaScript, file-drop transport, or CLI on disposable copies, but the full Gate A workflow has not been demonstrated as one no-GUI run with focus observed. |
| A02 | Manual Bass gain survives generation and accepted drum replacement | **Passed for the disposable A4 copy.** John's fader move was observed and saved. The installed replacement preserved exact silent Bass gain, pan, and ReaEQ through independent readback, native save, and reopen. The broader producer workflow is unqualified. |
| A03 | Manual Keys envelope survives unrelated edits, restart and export | **Prior A3 evidence plus disposable A4 pass.** The issue #10 qualification records John's manual Keys points, byte-identical copy, unrelated edits, save/reopen, and audible export. A4 preserved the earlier copied Keys lane through installed Drums replacement, save/reopen, and aligned export. The later `a3-probe` point was not recovered. |
| A04 | Overlapping edit blocks stale proposal without overwriting points | **Prior A3 evidence.** The corrected producer-edit run returned `CONFLICT` and preserved John's edited envelope chunk exactly. Earlier programmatic conflict checks also passed. |
| A05 | Envelope range boundaries and outside points are preserved | **Passed for the supported 1–3 second linear patch.** The native baseline, patched, and reopened envelope chunks show exact 0/4-second outside points and exact 1/3-second boundary points, including the outgoing right-point shape. The paired exports have zero exterior delta. Curved subdivision and automation items remain outside this adapter's supported patch contract. |
| A06 | Automation modes are observed without hidden mode changes | **Passed for the disposable automation fixture.** Native and installed-adapter reads agreed on modes 0–5 (Trim/Read, Read, Touch, Write, Latch, Latch Preview); the Keys lane and global override stayed unchanged during those observations. A bounded mode-1 patch left the native mode and override unchanged; the original mode was restored afterward. Earlier static-gain refusal checks and injected-host precondition tests still apply. |
| A14 | Pending writes cannot target a newly opened session | **Prior controller evidence, bounded.** The #9 environment report records switch-away-and-back rejection of an old session token. The token is callback-observed and does not guarantee detection of a switch entirely between callbacks; this does not qualify the A4 replacement path through installed transport. |
| A15 | Revert preserves later human work or refuses unsafe global undo | **Passed for a settled manual pan edit on a disposable copy.** After John moved the spare track pan to 0.592 and REAPER advanced the project revision, checked recovery returned `CONFLICT`. Immediate readback retained both the manual pan and patched Keys envelope; a saved, reopened copy retained both. The adapter never called global Undo. |
| A18 | Export includes accepted takes and audible manual automation with correct duration/tails | **Passed for the disposable zero-extra-tail fixture.** The native-saved and reopened installed replacement rendered at five seconds; aligned stems reproduced the mix, Bass was silent, the Keys envelope was audible, and Drums used the accepted source. Nonzero tails are unqualified, and the historical 45-second renderer timeout remains unexplained. |

For A05, an independent comparison of the retained
`automation-dxk76v2h` baseline, patched, and reopened envelope chunks found
exact `PT 0 1 0` and `PT 4 0.6 0` exterior lines, exact one- and three-second
boundary lines, a changed two-second interior point, and a byte-identical
patched/reopened chunk. The boundary comparison is recorded at
`/private/tmp/llm-studio-reaper/issue11-a06-a15-hcrpm8ko/a05-boundary-evidence.json`.
The earlier paired-export analysis found zero audio delta outside 1–3 seconds.

For A06, the first focused mode run observed all six values but its patch
applied natively and then failed Python readback because the adapter required
exact equality for a floating-point time sent through the bridge. Native
readback reconciled the changed lane; that dirty tab was left untouched and
the write was never retried. Fix `ad69cd3` allows only REAPER's eight-decimal
serialization budget in point time and positive gain while retaining strict
silence parity. Five focused regression cases and the full suite passed (121
passed, 8 skipped). A **fresh**, byte-identical disposable copy then passed the
six-mode installed-transport run, including a mode-1 patch. Evidence:
`/private/tmp/llm-studio-reaper/issue11-a06-a15-hcrpm8ko/a06-mode-evidence.json`
for the failed attempt and `a06-mode-retry-evidence.json` beside it for the
pass. Native mode 0 is REAPER's Trim/Read setting used for stopped manual
control; mode 1 is Read. No claim is made about recording automation during
transport playback.

For A15, an initial watcher triggered during John's first pan drag, before
the gesture settled; envelope-only recovery succeeded and later readback
found his pan retained. The runner wrongly required `CONFLICT` and did not
capture immediate post-recovery state, so that attempt is not a scripted pass.
The corrected watcher waited for a stable pan and a project revision beyond
the patch. In a new disposable copy, the settled pan was `0.592`, project
revision advanced from `3` to `5`, and checked recovery returned `CONFLICT`.
Immediate native readback held the same pan and exact patched Keys chunk. The
saved RPP had the spare `VOLPAN ... 0.592` and `PT 2 0.25 0`; an independent
reopen showed a clean four-track tab with the same values. Evidence:
`/private/tmp/llm-studio-reaper/issue11-a06-a15-hcrpm8ko/session-recovery-retry.RPP.a15-human-recovery-1790143129.txt`
and `reopen-recovery.txt` beside it.

The new installed replacement, save/reopen, and export checks passed with one
stable bridge owner. Bridge stop, immediate restart, and distinct-script owner
takeover passed in a separate disposable profile. A4's bounded renders show
the old renderer timeout did not reproduce in these attempts; they do not
explain or resolve that reliability failure.

**Gate A decision: no-go for full acceptance on this evidence.** The requested
A4 manual-gain, installed replacement, reopen, and zero-extra-tail export slice
passes in a disposable project. A05, A06, and A15 now pass within the stated
disposable-fixture bounds. A01 remains partial, and the historical renderer
timeout has no diagnosis. Keep PR #37 draft
and issue #11 open while those checks are resolved or explicitly narrowed by
the producer.

## Remaining acceptance

1. Demonstrate the complete Gate A DAW workflow through APIs/protocols while
   another application has keyboard focus. John clarified on 2026-09-24 that
   the eight-bar musical tracer remains Gate C. Existing API-only A3/A4 runs
   provide bounded evidence for several steps, but no run has covered the
   complete Gate A workflow with focus observed. Keep A01 partial until that
   demonstration is recorded.
2. Complete or explicitly narrow the remaining partial capabilities in the
   matrix. Never repeat the accepted replacement on an already changed tab.
3. Do not replace a script in the running producer profile.
4. Keep the historical renderer timeout as unresolved. Bounded reruns on a
   disposable fixture succeeded, but did not explain the earlier timeout.
