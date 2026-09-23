# Current handoff — issue #11 draft, live checks pending

## 2026-09-23 A05/A06/A15 continuation

The A05 retained baseline, patched, and reopened native envelope chunks were
compared again. The 0/4-second outside points and 1/3-second boundary points
are exact, the interior differs, and the patched/reopened chunks match. Prior
paired exports have zero delta outside 1–3 seconds. The Gate A matrix now marks
A05 passed for the supported bounded linear patch, with curved subdivision and
automation items outside the adapter contract. Evidence summary:
`/private/tmp/llm-studio-reaper/issue11-a06-a15-hcrpm8ko/a05-boundary-evidence.json`.

A first focused A06 run on `session-mode.RPP` observed all six distinct native
automation modes through the installed adapter with one unchanged Keys lane and
global override. Its mode-1 patch **applied natively** but the Python adapter
raised `patch readback differs` after receipt: the requested non-grid midpoint
was serialized with tiny floating-point differences, and the adapter compared
times exactly. Native readback reconciled the applied point at about 1.667
seconds and confirmed the runner restored the original mode. The project is
dirty and unsaved in its own tab; do not retry that write or save the tab.
Partial evidence:
`/private/tmp/llm-studio-reaper/issue11-a06-a15-hcrpm8ko/a06-mode-evidence.json`.
The adapter now allows only REAPER's eight-decimal precision budget while
retaining exact silence parity and rejecting material time/gain drift. Focused
tests passed 14/14; full suite passed 121 with 8 skips. Fix `ad69cd3` was
committed and pushed. A fresh, byte-identical `session-mode-retry.RPP` copy then
passed all six native/adapter mode readbacks through the installed bridge. The
Keys lane and global override stayed unchanged across the observation loop;
the mode-1 bounded patch passed with native/adapter mode 1 before and after,
and the original mode 0 was restored. Evidence:
`/private/tmp/llm-studio-reaper/issue11-a06-a15-hcrpm8ko/a06-mode-retry-evidence.json`.

For A15, John's first manual pan drag on a named spare track was detected while
still moving. Checked recovery succeeded and later independent native readback
showed the Keys envelope exactly restored and the manual pan retained at 0.592.
The first runner incorrectly required `CONFLICT` and failed before immediate
post-recovery readback, so this is strong bounded evidence rather than a clean
scripted pass. Its dirty `session-recovery.RPP` tab is preserved. A corrected
runner accepts either a scoped restore preserving pan or a conflict preserving
both edits, and waits for a settled pan plus a project revision. In a fresh
`session-recovery-retry.RPP` tab, John's second move settled at pan 0.592,
revision advanced from 3 to 5, and recovery returned `CONFLICT`. Immediate
readback retained both pan and patched Keys envelope. The saved RPP and a clean
four-track reopened copy retained pan 0.592 and Keys midpoint 0.25. Evidence:
`/private/tmp/llm-studio-reaper/issue11-a06-a15-hcrpm8ko/session-recovery-retry.RPP.a15-human-recovery-1790143129.txt`
and `reopen-recovery.txt` beside it. A05/A06/A15 now pass for their bounded
disposable fixtures. A01 and the historical renderer timeout still prevent a
full Gate A pass. Keep PR #37 draft and issue #11 open.

## 2026-09-23 bridge lifecycle follow-up

Sol reviewed the REAPER relaunch fault. The bridge patch now claims a fresh
process-local owner on every invocation, checks ownership before each queue
scan, and conditionally clears ownership on exit or explicit shutdown without
clearing a successor. The exact patch applies with both the strict bootstrap
installer and `git apply`; a mocked Lua host covers immediate rerun, old exit
after takeover, shutdown/restart, and late exit. The pinned-controller suite
passed 116 tests with 8 skips, including the Lua test. The fix was committed
and pushed as `0395cba`.

A separate licensed disposable profile at
`/private/tmp/llm-studio-reaper/issue11-rerun-0hhcwsdj/` installed that exact
patch; `bootstrap-verify` matched all four file hashes. REAPER launched without
a project argument, so the blank startup tab stayed blank. Deferred callbacks
ran without another audio-device or license dialog. A saved three-track manual
copy was opened in a second tab. The first installed bridge launch returned
three snapshots with one stable token. A second CLI invocation of the **same
script path** stopped replies. A native probe found deferred callbacks still
running, owner ExtState empty, and heartbeat aged by exit cleanup. A third
invocation started a new stable owner immediately, without a 15-second wait.
This is consistent with REAPER treating the second same-path action as a stop
toggle; that UI/action behavior is inferred from state, not documented as a
general rule. Do not prescribe blind double launches.

While that owner was active, a byte-identical bridge script at a distinct
filename claimed a new owner. Five snapshots shared one new token and the
project remained stopped with three tracks. `bridge.shutdown` returned success;
native readback found no owner, an aged ExtState heartbeat, working deferred
callbacks, and an unchanged project. One launch of the installed script then
restored a stable token across three snapshots. This qualifies owner takeover,
explicit stop, and immediate restart in one process with one disposable
resource. It does not coordinate separate REAPER processes sharing a resource.
The on-disk heartbeat file can look fresh for up to 15 seconds after shutdown.

Gate A is a **no-go for full acceptance** despite the A4 pass described below:
A01 remains partial, and the old renderer timeout remains
unexplained. Keep PR #37 draft and issue #11 open. Next work should address or
explicitly narrow those remaining capability checks without repeating the
accepted A4 replacement on an already changed tab.

## 2026-09-23 after audio-device selection

John selected an audio device in the new licensed instance at
`/private/tmp/llm-studio-reaper/issue11-owner-4yhg_yj8/`; no license dialog
appeared. The deferred probe gained `deferred=pass`, the installed bridge
heartbeat appeared, and four snapshots shared one token. The startup tab then
contained six in-memory tracks despite its three-track saved RPP. It was left
clean and untouched. A new uniquely named saved-manual-copy tab
`session-owner-qualified.RPP` opened with exactly three tracks; native tab
enumeration confirmed one selected target path, stopped transport, and the old
six-track tab unchanged.

Re-running the same installed bridge ReaScript stopped its replies. Native
ExtState inspection found its heartbeat stale. Sol reviewed this as consistent
with REAPER terminating the old running script before the new invocation
returns on the fresh-heartbeat startup guard. After the beat aged, one bridge
launch restored a stable token. A Luna child is implementing Sol's lifecycle
fix: every invocation claims a fresh owner token, and conditional `atexit`
cleanup must not clear a successor's ownership. Do not launch the current
bridge script a second time in a live instance just to test the guard.

With one stable owner and a fresh native tab proof, the guarded installed A4
helper made **one** Drums replacement in `session-owner-qualified.RPP` and
returned `ok: true`. Independent file-drop readback used the same token and
confirmed new media path, track/item/take binding and five-second geometry,
silent Bass with pan/ReaEQ, and unchanged Keys envelope. Evidence:
`/private/tmp/llm-studio-reaper/issue11-owner-4yhg_yj8/installed-a4-evidence.json`.
A guarded native save changed that RPP's SHA256 to
`90c44753ee58367f36f90418f968f9bebc9fa393b1876150745b886696a3cc44`
and serialized the new Drums path, Bass `VOLPAN 0 -0.2`, and Keys point
`PT 2 0.0419846`. The source tab still reported dirty after
`Main_SaveProjectEx`; preserve it.

A byte-identical saved RPP was opened in `session-owner-reopened.RPP`. Native
readback proved a clean three-track reopened tab with all original track,
item, and take GUIDs, exact Bass gain/pan/ReaEQ, the Keys lane, and the
accepted Drums source. The older startup tab remained clean and the qualified
source tab remained dirty. Evidence:
`/private/tmp/llm-studio-reaper/issue11-owner-4yhg_yj8/reopen-proof.txt`.
Headless mix and three-stem renders from the saved reopened RPP passed 220,500
aligned frames at 44.1 kHz, silent Bass, audible Keys automation, strong 440 Hz
Drums, and one-LSB maximum mix/stem error. Evidence:
`/private/tmp/llm-studio-reaper/issue11-live-saved-export-6m79wokj/mix-evidence.json`
and `/private/tmp/llm-studio-reaper/gate-a4-stems-nye0xhlr/audio-evidence.json`.
These are test tones, not human listening judgement. The zero-extra-tail
fixture and old renderer timeout limits remain. Gate A still has partial
capabilities; keep PR #37 draft and issue #11 open. Next: finish Sol review and
tests for the lifecycle patch, then requalify relaunch behavior on a separate
disposable profile without touching the accepted replacement tabs.

## 2026-09-23 latest continuation

John confirmed he moved the Bass fader in the uniquely named original-profile
handoff tab. Bridge readback found linear gain `1e-50` after `0.50118723362727`,
with pan, ReaEQ, and Keys points unchanged. A guarded native save of only that
tab wrote Bass `VOLPAN 0 -0.2` to
`/private/tmp/llm-studio-reaper/gate-a4-bass-handoff-5duxo9g9/session-bass-handoff.RPP`,
SHA256 `faf7cf49e91af503015f00086437804e50f78ef89dc18582e0e67b23ef91b6f6`.
The original tab still reported dirty; all older original-profile tabs were
preserved. The copy carries the earlier Keys point at two seconds `0.0419846`,
not the later saved `a3-probe` point.

John also licensed the isolated REAPER instance. Its bridge began responding.
The credential was not read or stored in the repository. An isolated tab at
`/private/tmp/llm-studio-reaper/issue11-installed-human-7y171ubg/session-human-bass.RPP`
opened from the saved manual RPP with exactly three tracks. Native tab checks
proved one selected target path, stopped transport, and unchanged older tabs.
The guarded installed helper made **one** `studio.replace_stem` call, which
returned the expected hash-addressed 440 Hz Drums source and preserved item/take
GUIDs. Its immediate independent read failed on a changed session token.
Subsequent read-only snapshots alternated between two startup nonces for the
same path/revision; `ps` found one REAPER process on this profile. This is a
duplicate bridge-handler ownership fault. Do not retry that replacement or
trust file-drop reads/writes until single-owner behavior is restored.

Native readback at
`/private/tmp/llm-studio-reaper/issue11-installed-human-7y171ubg/native-reconcile.txt`
found the new source in the unique dirty target tab, the expected track/item/take
GUIDs and five-second geometry, Bass gain `0` and unchanged pan/ReaEQ, plus
unchanged older isolated tabs. The saved isolated RPP still references the old
Drums source. A native save script first stopped on an overstrict revision
assertion; after adjusting that assertion, a forwarded script produced no
report, possibly due to a REAPER script-error dialog. John was asked to inspect
the isolated instance for a dialog. Do not claim save/reopen success yet.

An explicitly labeled offline copy of the saved manual RPP with only the native
observed Drums source path patched in rendered successfully. Evidence:
`/private/tmp/llm-studio-reaper/issue11-manual-export-_5e43jyr/offline-export-evidence.json`
and `/private/tmp/llm-studio-reaper/gate-a4-stems-39pu0q2d/audio-evidence.json`.
It has 220,500 aligned frames, silent Bass, audible Keys automation, strong
440 Hz Drums, and one-LSB maximum mix/stem error. This does not replace the
live save/reopen acceptance. A Luna child implemented a synchronous bridge
heartbeat reservation in the installed hook patch; Sol review and live
requalification remain pending. The license profile helper and silent-Bass
export checker were committed and pushed with the guarded replacement runner
at `dd9fc15`, `3abbbc7`, and `bfdf5a5`. Keep PR #37 draft and issue #11 open.

Next: review/commit the bridge owner guard, requalify on a fresh isolated
instance or fully stopped profile without disturbing the dirty target tab,
then complete a guarded native save/reopen if the isolated dialog is cleared.
Never repeat the already accepted replacement on the dirty target. The
historical render timeout still has no explanation.

The bridge owner guard was Sol-reviewed, passed a mocked Lua callback test and
the pinned-controller suite (116 passed, 8 skipped), and was committed as
`2e29299`. A new disposable profile at
`/private/tmp/llm-studio-reaper/issue11-owner-4yhg_yj8/` was created to test
it without touching the dirty earlier instance. The reviewed bootstrap plan
and receipt are in that directory; `bootstrap-verify` matched all four installed
file hashes. `install_profile_license.py` copied the existing protected license
file into the stopped new profile without displaying its contents. The new
REAPER process opened a clean three-track copy of the saved manual RPP in its
single tab. Native preflight passed on exact resource, project path, stopped
transport, track count and clean state. Launching the installed bridge yielded
no heartbeat/reply. A minimal deferred probe wrote `top=pass` but no deferred
marker, matching the earlier startup-dialog behavior; this is not evidence of
a bridge-guard failure. John was asked to dismiss any dialog in the new
instance. When callbacks run, observe three stable session tokens before one
new guarded replacement in that fresh project. Keep the old dirty target
untouched.

Updated: 2026-09-23. Branch: `codex/issue-11-gate-a`; PR head at review start
was `b884cfb`. Export-bound fix `679cefa` and pinned file-drop test `53e9d87`
were committed afterward. Guarded empty-profile bootstrap is `c775004`.
Draft PR: [#37](https://github.com/cotyledonlab/llm-studio/pull/37).
Issue [#11](https://github.com/cotyledonlab/llm-studio/issues/11) remains open;
Gate A is not accepted. Parallel issue #15 work is at draft PR #35 and must not
mutate live REAPER. PR #33 is merged and issue #10 closed.

Read [Gate A qualification](docs/qualification/reaper-gate-a.md) and the
[adapter contract](adapters/reaper/README.md) before continuing. This branch
implements same-length WAV replacement for a GUID-bound single-take item. The
corrected direct native run passed source replacement, stale-request
rejection, and track/item/take GUID comparisons across save/reopen. Evidence:
`/private/tmp/llm-studio-reaper/gate-a4-7rng30qk/native-evidence.txt`. Source
shape guards now require one empty track with the Keys envelope; the run passed
that precondition. Installed file-drop transport and manual Bass gain
acceptance remain open. The 45-second renderer timeout from #9 did not
reproduce in one bounded no-profile retry and remains unexplained. Keep PR #37
draft until Gate A is decided.

PR #37's local `origin/main...b884cfb` review found one actionable offline
gap: the export checker could accept mix and stems truncated to the same length.
The checker now compares all four WAV frame counts with the fixture's
full-project item bound. Read-only recheck of the retained files found 220,500
frames each at 44.1 kHz; this fixture has no extra tail. A new offline test
round-trips `studio.replace_stem` through the pinned controller's Python
file-drop client and a fake daemon. This does not qualify the live installed
Lua handler. The Gate A report now has a capability matrix. The local suite
passes 82 tests with 9 skips; the optional real-controller install test is
inapplicable because the adjacent controller checkout has advanced beyond
the pin. GitHub PR metadata/checks could not be fetched during this review.

## 2026-09-23 continuation

John reported no remaining REAPER dialogs. A read-only native probe found the
running `a3-probe` profile stopped with four tabs, three dirty; two tabs shared
the path `gate-a4-7rng30qk/session.RPP`. The original `a3-probe/session.RPP`
was no longer open. Do not use the old manual-handoff or take-replacement
runners: both assume that original tab, and path-only lookup cannot distinguish
the duplicate A4 tabs. Do not close or save any of the prior dirty tabs.

A new, byte-identical copy of the saved clean A4 RPP is at
`/private/tmp/llm-studio-reaper/gate-a4-bass-handoff-5duxo9g9/session-bass-handoff.RPP`.
Its offline inspection report is beside it. It has the earlier manually drawn
Keys lane (two-second raw gain `0.0419846`), not the later saved
`a3-probe/session.RPP` value `1.95447444`; do not claim it recovers a lost
in-memory edit. The unique copy was opened as a fifth tab without closing or
saving the four old tabs. Installed bridge readback in `before-manual.json`
recorded Bass linear gain `0.50118723362727`, pan `-0.2`, ReaEQ and the Keys
points. John was asked to move only this tab's Bass fader. No changed value or
producer confirmation had arrived at this update.

For separate installed-transport qualification, a pinned controller checkout,
bootstrap plan, receipt and new profile are under
`/private/tmp/llm-studio-reaper/issue11-installed-prep-20260923/`. The opt-in
empty-profile bootstrap guard was reviewed by Sol and tested; the full suite
passed 93 tests with 8 skips against that exact pinned checkout. An elevated
live process probe identified PID 23290 using the distinct `a3-probe` cfgfile.
The guarded apply installed four files only in the new empty resource;
`bootstrap-verify` matched their hashes before REAPER startup.

A second REAPER instance, PID 69313, uses only that new cfgfile and the copied
project `/private/tmp/llm-studio-reaper/issue11-installed-run-60evlc5m/session.RPP`.
One-shot scripts observed its exact resource, opened the copied project and
loaded the installed bridge script, but no heartbeat or file-drop reply
followed. Even a minimal `reaper.defer` probe wrote its top-level marker but
not its deferred marker. The cause is unproven; a startup/modal dialog blocking
the event loop is plausible. John was asked to check/dismiss any dialog in the
second instance. After that, retry only the minimal defer probe once with a
five-second bound. If it still does not run, stop bridge retries and record
installed runtime acceptance as pending. Do not count the installed file hashes
or offline fake-daemon test as live transport success.

## Prior REAPER ownership and producer state (2026-09-22)

Only this task may mutate the DAW. REAPER was using the disposable profile
`/private/tmp/llm-studio-reaper/a3-probe/profile/reaper.ini` at last inspection.
John had closed all but one tab. During continuation, the saved one-track
`automation-timebase-dk2qtrq9/project-1.RPP` fixture was opened for the native
run, along with disposable copies. A cleanup helper closed one clean test tab;
subsequent scripts produced repeated dialogs, and the current tab state is
unknown. John reported an error from `close_run_tab.lua`; stop REAPER work and
re-observe after the dialogs are cleared. Previously the original
`a3-probe/session.RPP` was dirty, and its **in-memory** two-second Keys
envelope point differed from the last saved source RPP. The source RPP on disk
was not changed by the test. Preserve any remaining producer state.

John was asked to move the Bass fader in the selected three-track copy, but
reported a dialog and that the project closed. A subsequent read-only native
tab enumeration showed both tabs still open and the original active. No manual
Bass edit has been observed or accepted; do not count the scripted -6 dB
fixture gain. The dialog's cause remains unknown.

The A4 copy and reports are under
`/private/tmp/llm-studio-reaper/gate-a4-693qi2_4/`; the mix and part WAVs are
under `gate-a4-export-rgwcznsd/` and `gate-a4-stems-yq1lv7j2/`. These are
temporary and may expire. The first sandboxed REAPER launcher aborted during
macOS application registration; it did not deliver the script and the old
process survived. Elevated forwarding of the exact same wrapper succeeded.
Opening the copy ended its running ReaScript; the second-stage readback script
completed. Do not repeat either failure path unchanged.

## Next bounded steps

1. After John reports the Bass move, observe the unique handoff copy again and
   prove a real gain change with unchanged session binding, pan, FX and Keys
   lane. Preserve all earlier dirty tabs and do not use path-only tab lookup.
2. After John checks the second instance for a dialog, repeat the minimal defer
   probe once. If it passes, check the installed daemon's heartbeat and run a
   fresh `studio.replace_stem` through the pinned file-drop client against the
   separate disposable profile. Verify save/reopen, bindings and export. If
   defer still fails, record the installed runtime gate as pending.
3. Finish the Gate A report and go/no-go decision from observed evidence. Do
   not close #11 or undraft PR #37 while these checks remain open.

---

# Prior handoff — issue #10 acceptance complete (historical)

Updated: 2026-09-22. Implementation branch: `feat/reaper-automation-handoff`.
PR: [#33](https://github.com/cotyledonlab/llm-studio/pull/33).
Issue #10 has a real producer-edit conflict observation. Check GitHub for the
current PR/issue state before resuming; issue #11 is the next Gate A slice.

Read [automation qualification](docs/qualification/reaper-automation.md) and
[adapter contract](adapters/reaper/README.md) before further live work.
Bounded native volume observation/apply and checked envelope-only recovery are
implemented. Before the producer-edit watcher correction, the pinned-controller
studio suite passed 72 tests with 8 optional integration skips. Native
copy-based qualification passed manual-lane copying, static-mode refusal,
programmatic intervening-edit conflict, exact recovery, refusal after unrelated
work, and patch save/reopen. Native global Undo restored pre-setup state in the
first probe; recovery now uses a checked compensating envelope transaction.

## Current live state

Only the issue #10 owner performed live writes; no GUI automation was used. The
disposable profile is running at
`/private/tmp/llm-studio-reaper/a3-probe/profile/reaper.ini`. John dismissed the
startup dialog. Always use this exact absolute `-cfgfile` when forwarding native
scripts; never automate the DAW GUI or edit active profile configuration.

The disposable source is `a3-probe/session.RPP`, with one `StudioAutomation`
track. John's latest manual edit changed the two-second point's saved linear
gain from 0.0419846 to 1.95447444. The one- and three-second points retain
linear gains 0.25118864 and 0.00120226. Re-observe the active tab before any
further live operation.
Envelope GUID: `{4C4BF0CF-8580-B941-98FE-60269BE60A4B}`. Preserve his edits.
Fresh evidence is under `automation-dxk76v2h/` and
`automation-timebase-lvgmrmj3/`. Installed transport patch/recovery, six
timebase cases, and exported-audio scope all pass on REAPER 7.80. The earlier
runner restored the original tab and preserved the source RPP bytes at that
time. The subsequent human edit intentionally changed the source RPP.
The older #9 profile and producer gain/pan adjustments were not opened/changed.

## Human conflict result and next work

The first armed run was a false positive: selection changed but the point's
time and gain did not. The corrected watcher required an actual time/raw gain
change and captured John's edit. It detected the change at age 10.709244 s
within the 30 s observation bound. The native handler returned `CONFLICT`,
applied no proposal, preserved the edited envelope chunk exactly and saved the
disposable source. Evidence:
`/private/tmp/llm-studio-reaper/human-conflict-20260922-retry.txt` (temporary).
The first failed attempt is `human-conflict-20260922.txt` and must not be cited
as a pass. A later review hardened the watcher with a ten-minute absolute
deadline, duplicate-owner exclusion, termination cleanup and an on-disk chunk
check after save. The passing run predates that hardening, but its saved RPP
was independently inspected and contained John's changed two-second point.

After PR #33 is merged, resume issue #11's take-replacement and export
investigation. The earlier
#9 `audio.render_project` timeout remains unresolved; the successful explicit
profile exports in #10 do not explain that failure. Do not repeat the same
timeout unchanged. The installed transport and native handler paths have
separate evidence in the qualification report.

---

# Prior handoff — issue #9 complete (historical)

Updated: 2026-09-08. Repository: `cotyledonlab/llm-studio`.
Resume branch: `main`. Implementation branch: `feat/reaper-studio-bootstrap`.
PR: [#32](https://github.com/cotyledonlab/llm-studio/pull/32).

## Current outcome and next step

**PR #32 is merged and issue #9 is closed.** Merge commit:
`3a6477a16c9b755e0c3246116f3131d84b130697`. Two Luna subagents reviewed
Standards and Spec; their shared recovery blocker was fixed in `d9fcaea`,
re-reviewed, and validated by 37 passing tests before merge. This is not a
full Gate A pass. The next implementation task is #10; it has not started.
Fetch main before resuming and do not duplicate the merged implementation. Review the qualified scope in
[`docs/qualification/reaper-environment.md`](docs/qualification/reaper-environment.md)
and [`adapters/reaper/README.md`](adapters/reaper/README.md).

The final producer action is complete: on laptop speakers John confirmed the
retried current-versus-quieter/hard-right audition with "yes that went as
expected". This is basic listening acceptance, not calibrated stereo or
musical-quality evaluation. The first audition was retried, not counted as a
pass. No further producer acceptance action is required for #9.

## Observed acceptance evidence

- External controller pinned and clean at
  `fd56d0008ffa5fba25cc58a70e5ae632c80b4c16`, in
  `/Users/johnmaher/code/reaper-controller`.
- REAPER 7.79 on macOS arm64. Upstream suite: 47 passed with host permissions.
  Latest studio suite: 37 passed with the actual pinned checkout enabled.
  Pre-merge review corrected temporary-file cleanup/retry in local bootstrap
  recovery; the installed daemon/handler and live mix were not changed.
- Reviewed bootstrap applied and verified while stopped in both the normal
  profile and a clean profile; clean repeat apply changed nothing. Normal
  profile changes were bridge/handler only; matching OSC and INI retained.
  Backups, rollback, running-process refusal and interrupted recovery have
  their documented test evidence.
- Native CLI launched the isolated profile/project and installed daemon.
  Python adapter discovery returned exact saved session, native track GUIDs
  and nonempty ReaSynth FX discovery (18 parameters).
- Installed adapter gain/pan writes, independent readback and restoration
  passed. Actual content-addressed one-second WAV import at 4s returned source,
  item GUID, position and length.
- OSC play/stop feedback, advancing timecode and nonzero VU passed. Bridge
  shutdown/restart returned a fresh token and rejected the old token.
- Native-handler qualification previously passed two-track GUID rename/reorder,
  deletion/session-switch rejection and durable import. Prior objective render
  evidence measured right RMS ratio 0.4999999862, hard-right left RMS zero.
- John manually moved StudioQualification to displayed -5.99 dB; the installed
  adapter returned -5.992185001375451 dB with matching GUID and session token.
  His first adjustment was MASTER, correctly distinguished by readback.
- Live listening retry: two 2.8s passes separated by 3s; B had half linear gain
  and hard-right pan. Producer accepted. Independent final readback confirmed
  exact restoration of his track gain and centre pan.

## Current live state and local artifacts

Re-observe before any new DAW action. The last observed instance was the clean
profile on disposable `adapter-session`, stopped after the audition.

Evidence root: `/private/tmp/llm-studio-reaper/qualification-20260908/`.
Profile: `clean-profile/reaper.ini`; project: `adapter-session.RPP`.
Track `StudioQualification`: GUID `{B241E427-5B68-480D-AA41-6CC0F28DA872}`,
linear gain 0.5016383722284, pan 0. MASTER also manually lowered to about
-5.99 dB. Preserve both producer adjustments. StudioImport remains unity.

Key artifacts: `installed-checks.jsonl`, `osc-evidence.json`,
`restart-evidence.json`, `manual-fader-evidence.json`,
`listening-retry-evidence.json`, `producer-listening-confirmation.json`,
`accepted-final-snapshot.json`. Prior render evidence is under
`/private/tmp/llm-studio-reaper/qualification-6sk64bx9/`. Temporary evidence may
expire; durable results and qualified limitations are in the committed report.

Normal-profile rollback receipt: `qualification-20260908/profile-receipt.json`.
Durable recovery receipt:
`~/Library/Application Support/REAPER/LLMStudioBackups/bootstrap-af5892127fad44a4a01e7a19c713ebf4/result.json`.
Rollback requires all REAPER instances stopped and unmodified targets. Do not
reapply configuration while the test instance runs. Normal-profile file install
is verified; its runtime activation is not established by the isolated test.

## Known failures and boundaries

- Alternate-profile native script forwarding **must include the same absolute
  `-cfgfile`** with `-nonewinst -noactivate`. Omitting it started an extra
  normal-profile process, which the agent terminated. The guarded read-only
  script produced no observation file there; its execution was not established.
  The corrected invocation reached the isolated instance. Do not claim global
  producer-profile state was unchanged by that application's own startup.
- Initial clean-profile startup probe timed out, then the daemon became active.
  No producer report identified a startup dialog; its cause is unknown.
- A fresh optional render A/B using upstream `render_project(..., timeout=45)`
  timed out without a WAV. The mixer had already been restored. Do not erase
  this failure with the prior native render pass or live listening acceptance.
  Reproduce and resolve it in #11 before claiming reliable export. Explicit
  profile selection is a hypothesis, not a verified renderer fix.
- Session tokens are callback observations, not production write leases; a
  switch away/back entirely between callbacks is not guaranteed detectable.
  Import timeouts must not be retried blindly. WAV-only import is qualified.
- No producer-project writes, envelopes, conflict protocol or coordinator are
  implemented by this slice. The controller declares MIT but lacks a standalone
  licence notice; #30 covers notices/outgoing licensing before distribution.
  REAPER purchase/activation remain producer actions; evaluation is explicit.

## Mission and subsequent work

Build the smallest producer-led workflow where agents create/revise takes and
John retains authoritative manual control of the accepted REAPER project.
Read `CONTEXT.md`, `SPEC.md`, the REAPER ADR and `docs/IMPLEMENTATION_PLAN.md`.
Issue tracker status is authoritative. Ardour #8 is closed historical no-go;
SuperCollider #12 and Pedalboard/Dexed #13 have real qualification evidence.

#10 next addresses envelope fidelity, stale-state rejection or
explicit handoff, and safe undo. #11 covers mix-preserving take replacement,
binding recovery, save/reopen and export (including the render timeout above).
Gate B still needs catalogue #14 and isolation/alignment #15. #31 provisioning
is deferred convenience, not permission to install plugins during qualification.

## Safety and working rules

- Only one agent/process may mutate live REAPER. Background renderers must not
  acquire its audio device. Never automate the DAW GUI.
- Follow adjacent controller `AGENTS.md`, `skills/reaper/SKILL.md`, README,
  SPEC, pitfalls and ticket reports before invoking/changing it.
- Mutate only disposable projects under documented scratch/test paths unless
  John explicitly names a real project. Read back every mutation.
- Preserve producer edits. Never edit active REAPER preferences or bypass
  uncertain/running-process detection. Sandbox process checks can fail; obtain
  host access rather than interpreting failure as stopped.
- Do not commit generated audio/projects, plugins, samples, credentials or
  private recordings. Commit and push working states. User requested cheaper
  subagents for independent work; keep live DAW ownership with the primary.
