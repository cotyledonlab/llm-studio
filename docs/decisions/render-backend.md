# Decision: Python plugin render backend

- Status: accepted for the first implementation gate
- Date: 2026-09-05
- Issue: #13

## Decision

Use Spotify Pedalboard as the single Python plugin-rendering backend. Start with
the qualified Dexed 1.0.1 VST3 factory patch on the pinned Apple Silicon host.
Keep SuperCollider NRT as the separate existing-synthesis worker; it is not a
Python plugin host alternative.

Pedalboard loaded a real installed VST3 instrument without a GUI or audio
device, exposed parameter metadata, restored raw patch state after process
restart, honoured scheduled note and sustain messages, and rendered aligned
stereo float audio at the requested sample rate. The exact evidence and limits
are in [the qualification report](../qualification/pedalboard-rendering.md).

## Alternative

Do not add DawDreamer now. No required Pedalboard capability failed during the
bounded bake-off, so a second native hosting stack would add installation,
crash-isolation, state-format, and compatibility work without addressing an
observed requirement. Evaluate it only against a named plugin or scheduling/
automation requirement that Pedalboard demonstrably cannot satisfy.

## Consequences

Workers must pin and hash the host, plugin binary, and patch state. Controller
support is opt-in per instrument mapping. Native plugins run in disposable
processes, and a crash or timeout must never affect Ardour. Rendered timbre
automation remains baked; only performance and patch state enable revision.
