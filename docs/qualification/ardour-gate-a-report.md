# Gate A qualification report

Date: 2026-09-05

Issue: #8 — qualify a no-purchase macOS Ardour build and discover native APIs

Decision: **NO-GO for Ardour-backed implementation on the current baseline**

## Outcome

The target Mac has no installed or running Ardour build. A current upstream source checkout was obtained without purchase, but configuration failed at the first missing build dependency (Boost). Upstream's own macOS guidance requires a separately built dependency stack, described by its FAQ as 89 other libraries. Consequently, no actual MCP server, installed tool schema, session operation, or endpoint binding could be qualified.

This is a bounded no-go, not a claim that Ardour or its source build can never work. It means issues #9–#11 must not implement against assumed MCP behavior yet.

## Acceptance criteria

| Issue #8 criterion | Result | Evidence |
|---|---|---|
| No mandatory paid entitlement and no automated GUI input | **Failed overall** | Source was freely obtainable and no GUI automation was used, but no runnable no-purchase build was produced |
| Actual installed schemas and gaps committed with version evidence | **Failed** | There is no installed build. Upstream source commit and source-only gaps are recorded separately; they are not called installed evidence |
| Loopback verified or exposure corrected | **Failed / unknown** | No process existed to test. Source and current manual create enough ambiguity that runtime socket verification is mandatory |
| Missing essential capability yields bounded no-go | **Passed** | This report stops before a speculative connector and records the required decision |

## Gate A checks

| Check | Result |
|---|---|
| Obtain/run no-purchase build | **Failed** — source obtained; configure failed; nothing runnable |
| Discover actual MCP tools and endpoint exposure | **Unknown** — no runtime endpoint |
| Create/bind session, stable IDs, audio insert, gain/pan | **Unknown** |
| Read back producer fader and envelope edits | **Unknown**; envelope read is an apparent native-schema gap |
| Apply envelope, undo, save/reopen | **Unknown**; envelope write is an apparent native-schema gap |
| Conflict handling | **Unknown**; no atomic check/apply operation was found in the source schema |
| Replace part while preserving mix/processing/automation | **Unknown** |
| Export stereo mix reflecting automation | **Unknown**; no audio export tool was found in the source schema |

Gate A remains open as a product gate but this qualification task returns no-go on the current environment. The essential envelope readback and safe-conflict requirements have no runtime evidence; the specification explicitly makes either failure blocking.

## Security finding

The current manual says the server listens on all interfaces by default. The inspected source advertises a loopback URL but does not visibly set a bind interface when creating the libwebsockets context. Neither is runtime proof. A future build must be started, then checked with `lsof -nP -iTCP:<port> -sTCP:LISTEN` and connection attempts via loopback and a non-loopback host address. Do not expose it beyond loopback without authentication.

## Decision required before issue #9

Choose one of these bounded paths:

1. Provide a pinned, reproducible Apple Silicon dependency-stack build and rerun issue #8's runtime probe; or
2. Approve an official paid build only as an optional convenience while still supplying a no-purchase baseline; or
3. Revisit the DAW choice because the no-purchase macOS source-build requirement is presently impractical.

If a runnable build is supplied, first capture its actual `tools/list` response. If envelope read/write, audio import, export, notifications, and atomic conflict application are still absent, timebox a narrow in-process/Lua adapter assessment. Do not start a general connector.

## Evidence and references

- [Environment and source-build attempt](ardour-environment.md)
- [Capability matrix](ardour-capability-matrix.md)
- [Read-only MCP discovery probe](../../scripts/probe-ardour-mcp.sh)
- [Failed runtime probe evidence](evidence/2026-09-05-mcp-probe.txt)
- [Failed source configure evidence](evidence/2026-09-05-source-configure.txt)
- [Official Ardour macOS source-build instructions](https://ardour.org/building_osx_native.html)
- [Official Ardour build dependencies](https://ardour.org/current_dependencies.html)
- [Official Ardour FAQ](https://ardour.org/faq.html)
- [Official MCP HTTP manual](https://manual.ardour.org/using-control-surfaces/mcp-http/)
- [Upstream source used for source-only observations](https://github.com/Ardour/ardour/commit/ba38f08ea4e63ae3b8c39405e61239aa7d490f2a)

No screenshot, GUI automation, mock, paid build, or documentation-only capability was counted as runtime evidence.
