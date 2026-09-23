# REAPER Gate A / issue #11 qualification

Updated: 2026-09-23. **Technical A4 copy-based checks pass; Gate A is not yet
accepted.** The human Bass move was observed and copied, but the installed
file-drop transport has duplicate handlers and the new take has not passed
save/reopen and export. This report does not replace the completed [A3 automation
qualification](reaper-automation.md) or claim the old renderer timeout is fixed.

## Scope and builds

Host: REAPER `7.80/macOS-arm64` on macOS 26.5.2. Controller protocol remains
pinned at `fd56d0008ffa5fba25cc58a70e5ae632c80b4c16`; the adjacent
checkout currently includes one later instruction-only commit. The first A4
native run loaded this branch's `studio_handler.lua` directly inside a REAPER
ReaScript. Installed file-drop transport for the new replacement operation is
not yet qualified. All project writes were to a disposable copy.

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

## Gate A capability matrix

Statuses refer to the stated evidence scope; copy-based qualification does not
by itself establish the complete producer workflow.

| SPEC ID | Capability | Status and evidence |
|---|---|---|
| A01 | Core tracer through APIs/protocols without GUI automation | **Partial.** A3 automation and A4 replacement/export used native APIs, ReaScript, file-drop transport, or CLI on disposable copies. This slice has not completed the full core tracer while another application has keyboard focus. |
| A02 | Manual Bass gain survives generation and accepted drum replacement | **Partial.** John's fader move was observed and saved in a disposable handoff RPP. The separate installed replacement preserved exact silent Bass gain, pan, and ReaEQ in native post-state. Save/reopen of that replacement is pending. |
| A03 | Manual Keys envelope survives unrelated edits, restart and export | **Prior A3 evidence.** The issue #10 qualification records John's manual Keys points, byte-identical copy, unrelated edits, save/reopen, and audible export. A4 also preserved the copied Keys envelope through Drums replacement and export. The final Bass-dependent A4 workflow is still pending. |
| A04 | Overlapping edit blocks stale proposal without overwriting points | **Prior A3 evidence.** The corrected producer-edit run returned `CONFLICT` and preserved John's edited envelope chunk exactly. Earlier programmatic conflict checks also passed. |
| A05 | Envelope range boundaries and outside points are preserved | **Partial, prior A3 evidence.** Native bounded patch and export checks preserved points outside the edited interval and the right endpoint shape; injected-host checks cover additional boundary cases. No complete Gate A envelope scenario is claimed. |
| A06 | Automation modes are observed without hidden mode changes | **Partial, prior A3 evidence.** Static gain writes were refused across six native automation modes, and mode/transport/global override refusals have injected-host coverage. Distinct mode observation and end-to-end no-mode-change acceptance remain unqualified. |
| A14 | Pending writes cannot target a newly opened session | **Prior controller evidence, bounded.** The #9 environment report records switch-away-and-back rejection of an old session token. The token is callback-observed and does not guarantee detection of a switch entirely between callbacks; this does not qualify the A4 replacement path through installed transport. |
| A15 | Revert preserves later human work or refuses unsafe global undo | **Partial, prior A3 evidence.** Checked envelope-only recovery restored the target and refused after an unrelated track edit; the unsafe global Undo path was removed. A recovery-after-human-edit case is not recorded. |
| A18 | Export includes accepted takes and audible manual automation with correct duration/tails | **Prior copy-based evidence passes for this zero-extra-tail fixture.** A4 rendered the earlier reopened, replaced-take project at five seconds; aligned stems reproduced the mix and the Keys envelope was audible. Export after John's Bass move and the new installed replacement is pending. Nonzero tails are unqualified, and the historical 45-second renderer timeout remains unexplained. |

The installed replacement returned success and its native post-state matches,
but duplicate bridge handlers prevent a reliable single-owner transport
qualification. The new replacement's save/reopen/export check remains pending.
A4's bounded renders show the old renderer timeout did not reproduce
in these attempts; they do not explain or resolve that reliability failure.

## Remaining acceptance

1. Resolve duplicate bridge-handler ownership in the isolated profile, then
   requalify single-owner request/reply behavior without repeating the already
   accepted replacement on the dirty tab.
2. Save/reopen the isolated replacement only after its native guarded save can
   run, then verify exact Bass gain, Keys envelope, FX, media references, and
   aligned audible export. Keep the earlier tabs intact.
3. Do not replace a script in the running producer profile.
4. Review the implementation and full Gate A capability matrix, then make an
   honest go/no-go decision. Keep the historical renderer timeout as unresolved
   unless a bounded reproduction explains it.
