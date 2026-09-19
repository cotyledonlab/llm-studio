# Minimal instrument catalogue qualification (issue #14)

Date: 2026-09-19. Status: **Orb implementation complete; native rendering and
producer audition pending on the pinned Apple Silicon studio host**.

## Catalogue boundary

The packaged schema in `src/llm_studio/catalogue_data/catalogue.json` defines
exactly three initial IDs:

| Catalogue ID | Role | Backend | State and assets |
|---|---|---|---|
| `studio.drums.sc-basic-v1` | Electronic kit | SuperCollider 3.14.1 NRT, build `426edf6` | Repository-authored stock-UGen state; no samples |
| `studio.bass.sc-pulse-v1` | Synth bass | SuperCollider 3.14.1 NRT, build `426edf6` | Repository-authored stock-UGen state; no samples |
| `studio.keys.dexed-factory-v1` | FM keys | Pedalboard 0.9.24 and Dexed VST3 1.0.1 | Factory state hash and exact plugin executable hash; no cartridge or samples |

Each entry records a stable ID, backend version/build identity, canonical state
hash, asset provenance and licence facts, playable range, controller/keyswitch
and drum mappings, and a content-addressed audition fixture. The catalogue and
fixtures contain no audio, native binaries, plugin state blobs, or restricted
assets.

`llm-studio catalogue-list` resolves the three IDs without importing either
native renderer. `llm-studio catalogue-check ID` verifies the pinned runtime,
Python distribution version, plugin location, and plugin SHA-256 before use.
An unknown ID, missing dependency, version mismatch, or hash mismatch is a hard,
actionable error; the loader never chooses a substitute sound.

All three entries deliberately remain `candidate`. The prior reports qualify
the SuperCollider NRT mechanism and Pedalboard/Dexed factory-state mechanism,
not these new sounds or performance fixtures. A schema test cannot promote an
entry to `qualified`.

## Deterministic audition fixtures

The committed fixtures are short, dry 48 kHz performances with explicit start
silence and tail:

- drums exercise kick, snare, and closed-hat mappings;
- bass exercises sustained notes across an overlapping phrase;
- keys exercise a triad, overlapping notes, and the declared CC64 mapping.

Their canonical JSON hashes are pinned in each entry. Any edit therefore
requires an explicit catalogue revision rather than silently changing the
qualification phrase.

`tools/qualification/catalogue_audition.py` validates declared ranges and
mappings, builds the reviewed stock-UGen drum/bass SynthDefs or the complete
Dexed MIDI schedule, renders a 32-bit float WAV atomically, and publishes a
content-addressed measurement manifest. Example studio-host commands are:

```sh
PYTHONPATH=src:. .venv-sc-qualification/bin/python \
  tools/qualification/catalogue_audition.py studio.drums.sc-basic-v1 \
  --output /tmp/studio-drums.wav
PYTHONPATH=src:. .venv-pedalboard-qualification/bin/python \
  tools/qualification/catalogue_audition.py studio.keys.dexed-factory-v1 \
  --output /tmp/studio-keys.wav
```

## Orb verification

The secure Linux Orb does not contain `scsynth`, Pedalboard, or the macOS Dexed
VST3 binary. The deterministic checks cover schema/state/fixture integrity,
exact ID lookup, no-substitution behavior, version checks, missing dependency
diagnostics, and plugin binary hash rejection. The native dependency check was
also exercised and returned the expected exact `scsynth 3.14.1` installation
error. No render or listening claim is made from this environment.

## Required studio-host handoff

On the same pinned host used for issues #12 and #13:

1. Render the committed drum and bass fixtures through the reviewed named
   stock-UGen SynthDefs and `scsynth -N`.
2. Load exact Dexed 1.0.1 through Pedalboard 0.9.24, verify its captured raw
   factory state hash before scheduling the keys fixture, and render offline.
3. Restart each worker and repeat. Record backend/build hashes, state and audio
   hashes, load/render time, peak, RMS, onset, release tail, CPU and peak RSS.
4. Confirm drum-map events, overlapping bass/keys notes, and CC64 behavior;
   reject clipping, missing events, range errors, and undeclared substitutions.
5. Have the producer audition the three renders. Only then update each entry's
   qualification status and evidence reference.

Audio, plugin binaries, generated native state, credentials, and restricted
assets stay outside git. Until this handoff passes, issue #14 and Gate B remain
open and callers must present these sounds as candidates rather than qualified
instruments.
