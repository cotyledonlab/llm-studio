# REAPER automation qualification — issue #10

Updated: 2026-09-09. **In progress; not a Gate A pass.**
Implementation: `feat/reaper-automation-handoff`, initial implementation `81782cb`.
Controller remains pinned at `fd56d0008ffa5fba25cc58a70e5ae632c80b4c16`.
Native host: REAPER `7.79/macOS-arm64`, fresh disposable profile.

## Contract and limits

See [adapter contract](../../adapters/reaper/README.md#volume-envelope-qualification--issue-10).
Only disposable sessions are writable. The handler compares exact cached native
envelope state and project revision within the synchronous apply callback.
It rejects expired, evicted or consumed observations and stopped-session/mode
precondition failures. Any observed project edit causes conservative conflict.
This is a qualification API, not a coordinator or production write lease.

Points use project seconds. Raw fader values are converted using REAPER's
[documented scaling APIs](https://www.reaper.fm/sdk/reascript/reascripthelp.html#GetEnvelopeScalingMode).
Project and track timebase settings are captured; envelope beat-attachment
preferences and tempo-change behavior remain unqualified. No beat-domain edit
is exposed. The bounded patch requires existing unique endpoints with unchanged
gains and preserves the right point's outgoing shape/tension. Only new linear
segments are offered; arbitrary nonlinear subdivision is not claimed.

## Native evidence

Local evidence: `/private/tmp/llm-studio-reaper/automation-y8d1mjbr/`.
Source manual session: `/private/tmp/llm-studio-reaper/a3-probe/session.RPP`.
Profile: `a3-probe/profile/reaper.ini`. Generated RPP/WAV files stay outside git.

John confirmed: “I've moved points at 1 2 and 3”. Native readback captured:

| Time (seconds) | Saved linear gain |
|---|---:|
| 0 | 1 |
| 1 | 0.25118864 |
| 2 | 0.0419846 |
| 3 | 0.00120226 |
| 4 | 0.6 |

Native envelope GUID: `{4C4BF0CF-8580-B941-98FE-60269BE60A4B}`.
The runner copied the lane byte-for-byte into a new disposable tab. It did not
apply a successful proposal to John's original lane. `native-evidence.txt`
records:

- Static gain writes refused in all six modes (Trim/Read, Read, Touch, Write,
  Latch and Latch Preview); original envelope chunk unchanged.
- Five-second generated tone durably imported into the copy.
- A native API edit between observation and application caused `CONFLICT`,
  preserving the intervening points exactly. This edit was programmatic,
  not human evidence.
- Accepted 1–3 second patch returned observed points, preserved the unrelated
  track chunk, and had a unique named undo transaction.
- Checked compensating recovery restored the exact original envelope chunk.
- An unrelated native edit to another track caused recovery refusal; its pan
  remained at 0.25.
- Patched envelope chunk survived save/reopen exactly.
- Original source tab restored and source project revision unchanged.

## Recovery finding

The first native probe applied a patch successfully but its global Undo restored
an earlier, empty/inactive lane. Setup edits made directly by a script were not
captured as the previous native undo state. Exact before/after chunks made this
failure reproducible; it was not dismissed as a metadata difference.

The adapter now performs a compensating **envelope-only** restore in a named
transaction after exact target and project-revision checks. It never calls
`Undo_DoUndo2`. The original probe passed after this change, and the repeatable
copy-based native runner passed both immediate recovery and refusal after
unrelated work. Failed partial application restores the captured envelope chunk
inside the current callback; failed restoration is reported as uncertain.

## Deterministic verification

The full suite with the actual pinned controller passed **43 tests**. The new
Lua contract executes the actual handler against an injectable host and covers
changes without revision notifications, unrelated revision changes, expiry,
range/GUID mismatch, endpoint gain mismatch, mode/transport/global overrides,
automation-item refusal, partial insertion failure with exact restoration,
consumed receipts, outside/right-point preservation and recovery refusal.
Python tests cover dB conversion and malformed or mismatched readback. Simulated
tests do not qualify host behavior.

Native runner (requires the named source active and stopped):

```sh
python3 tools/qualification/reaper_automation.py \
  --source /private/tmp/llm-studio-reaper/a3-probe/session.RPP \
  --cfgfile /private/tmp/llm-studio-reaper/a3-probe/profile/reaper.ini --run
```

## Outstanding

- Actual intervening human-edit rejection, distinct from native API simulation.
- Updated installed handler through the pinned Python controller transport.
- Exported audio verification of the range and unchanged exterior.
- Envelope beat-attachment/timebase semantics and quantitative freshness latency.
- Full A03–A06/A15 acceptance review, including the limits of synchronous
  serialization for human-edit ordering. No artificial mid-callback UI edit is
  claimed, and no atomicity claim is made for arbitrary external extensions.

The previous #9 renderer timeout remains unresolved for #11. This report does
not claim musical quality or listening acceptance for the automation patch.
