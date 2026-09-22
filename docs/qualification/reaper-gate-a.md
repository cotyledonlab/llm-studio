# REAPER Gate A / issue #11 qualification

Updated: 2026-09-22. **Technical A4 copy-based checks pass; Gate A is not yet
accepted.** The final human Bass-fader check, installed-transport readback, and
review remain open. This report does not replace the completed [A3 automation
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

## Remaining acceptance

1. John was asked to change Bass gain in the disposable three-track tab, but
   reported a dialog and that the project closed. No manual edit was observed
   or counted. A read-only REAPER probe found the app still running and both
   tabs still open at that time. Later qualification tab cleanup produced
   repeated dialogs and the current state is unknown. Stop REAPER operations
   until the app state is re-observed and the dialogs are cleared.
2. After a verified manual Bass move, replace the Drums source again with a
   fresh observation, save/reopen, and independently verify the exact gain,
   Keys envelope, FX, media references and audible export.
3. Qualify the new operation through the installed pinned-controller transport
   in a separate disposable profile. Do not replace a script in a running
   producer profile.
4. Review the implementation and full Gate A capability matrix, then make an
   honest go/no-go decision. Keep the historical renderer timeout as unresolved
   unless a bounded reproduction explains it.
