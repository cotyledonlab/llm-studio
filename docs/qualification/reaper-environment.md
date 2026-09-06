# REAPER integration qualification — issue #9

Date: 2026-09-06. Status: implementation in progress; **not a Gate A pass**.

## Baseline observed this session

- Studio handoff commit: `00314ad` (initial local checkout clean on `main`).
- External controller: `/Users/johnmaher/code/reaper-controller`, clean at
  `fd56d0008ffa5fba25cc58a70e5ae632c80b4c16`.
- REAPER binary: `/Applications/REAPER.app/Contents/MacOS/REAPER`.
- Version: `7.79.0_06dd787u`; evaluation notice present. Purchase and activation
  remain producer actions and are not claimed complete.
- Controller `doctor`: overall OK; resource directory, default OSC resources,
  render flags and bridge queues present; daemon alive; no orphan requests.
- Controller `status`: daemon alive; OSC receive, feedback and Web Remote
  ports reported occupied. Port occupancy alone does not prove protocol health.
- Existing OSC surface line matches the controller's documented Agent surface
  (`8000`, feedback `127.0.0.1:9000`). Existing bridge action is registered.
- Controller tests excluding native MIDI and socket loopbacks:
  `.venv/bin/python -m pytest -q -p no:cacheprovider --ignore=tests/test_midi.py -k 'not loopback and not capture'`
  → **43 passed, 2 deselected**. This is deliberately not the complete suite.
- Complete controller suite with required host permissions:
  `.venv/bin/python -m pytest -q -p no:cacheprovider`
  → **47 passed in 1.65 seconds**.

No producer project, preferences, installed scripts or plugins were modified
by these checks. File-drop discovery needs permission to write the controller
queue even when the requested REAPER operation is read-only.

## Integration adjustment

Reuse the controller as an external pinned checkout; do not vendor its generic
bridge. Its current bridge can return a GUID when adding a track, but subsequent
mix operations target indices. It lacks session identity, full GUID discovery
and durable audio import. A narrow studio handler loaded by the existing bridge
is required. Session and GUID checks must execute inside its serialized REAPER
callback; a Python read followed by an index write would not preserve identity
across producer edits.

The extension uses the official [ReaScript API](https://www.reaper.fm/sdk/reascript/reascripthelp.html).
API documentation and simulated tests establish implementation intent; only
observed replies and actual renders qualify this integration.

The controller declares MIT in `pyproject.toml` but has no standalone LICENSE
file at the pin. Private reuse continues through the external checkout. Obtain
the upstream copyright/licence notice and choose the studio's outgoing licence
before distribution. See `adapters/reaper/controller-pin.json`.

## Remaining acceptance evidence

- Bootstrap preview, backup, idempotent apply, verification and rollback on a
  disposable resource tree, followed by real installation verification.
- Studio extension activation and observed capability/session discovery.
- Disposable-project GUID binding through rename/reorder, explicit orphaning
  after deletion, and rejection following session switches.
- Durable stem import, native mixer/FX readback and rendered gain/pan evidence.

Issue #9 remains open until its real acceptance evidence exists. Issues #10,
#11 and the coordinator remain dependent work. Loading/reloading a ReaScript
may need a precise producer action; do not automate the DAW GUI to bypass it.
