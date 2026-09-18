# Current handoff — issue #10 in progress

Updated: 2026-09-09. Resume branch: `feat/reaper-automation-handoff`.
Draft PR: [#33](https://github.com/cotyledonlab/llm-studio/pull/33).
Implementation `81782cb`, native runner/report `099faf5`, both pushed.
Issue #10 remains open. Do not merge or claim Gate A complete.

Read [automation qualification](docs/qualification/reaper-automation.md) and
[adapter contract](adapters/reaper/README.md) before further live work.
Bounded native volume observation/apply and checked envelope-only recovery are
implemented. The full pinned-controller studio suite passed 43 tests. Native
copy-based qualification passed manual-lane copying, static-mode refusal,
programmatic intervening-edit conflict, exact recovery, refusal after unrelated
work, and patch save/reopen. Native global Undo restored pre-setup state in the
first probe; recovery now uses a checked compensating envelope transaction.

## Current live state

Only the primary owns live writes; no subagents were used. REAPER was stopped
at the start of this session. A fresh disposable profile was launched at
`/private/tmp/llm-studio-reaper/a3-probe/profile/reaper.ini`. John dismissed the
startup dialog. Always use this exact absolute `-cfgfile` when forwarding native
scripts; never automate the DAW GUI or edit active profile configuration.

Original active tab is `a3-probe/session.RPP`, with one `StudioAutomation` track.
John manually moved points at 1, 2 and 3 seconds and confirmed it in conversation.
Captured linear gains were 0.25118864, 0.0419846 and 0.00120226 respectively.
Envelope GUID: `{4C4BF0CF-8580-B941-98FE-60269BE60A4B}`. Preserve his edits.
The runner saved a copy and restored the original tab with its revision unchanged.
The copy `automation-y8d1mjbr/session.RPP` contains the qualification patch and
an unrelated control track; its complete native evidence is in that directory.
The older #9 profile and producer gain/pan adjustments were not opened/changed.

## Pending producer action and next work

John was asked to move the 2-second point once more to test actual human-edit
rejection. The first three-minute watcher timed out without detecting an edit;
its result is `a3-probe/manual-conflict-timeout.txt`. A new ten-minute watcher
was armed from `a3-probe/manual-conflict.lua`; inspect `manual-conflict.txt` before
any further DAW action. Do not start another live mutator while it runs.
It only attempts a proposal after detecting a changed envelope chunk, which must
be rejected against the old observation. It records elapsed time and exact
point/revision preservation. Observations expire after 30 seconds: if the human
edit happens later, report expiry as a possible rejection reason rather than
claiming a within-freshness fingerprint-only human test. The native programmatic
edit test separately demonstrated exact state mismatch rejection.

Once this watcher finishes, save the disposable manual tab without losing edits.
Remaining work: updated installed bridge/Python transport qualification (stop
REAPER safely before bootstrap), exported audio comparison, envelope attachment/
timebase semantics, quantitative polling freshness, and A03–A06/A15 review.
Do not treat the native direct-handler runner as installed-transport evidence.
The new runner requires exact active source/profile and waits for its observed
completion; source revision or native assertion failures make the CLI fail.

Keep issue #10 and PR #33 open until acceptance is established. The #9 renderer
timeout still belongs to #11; it has not been resolved by this session.

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
