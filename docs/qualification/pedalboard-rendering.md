# Pedalboard instrument qualification (issue #13)

Date: 2026-09-05. Host: Apple Silicon Mac (`arm64`), macOS 26.5.2. Result:
**adopt Pedalboard with Dexed VST3 as the initial Python plugin worker**.

## Candidate and setup

The existing real instrument selected for the bounded session was Dexed VST3
1.0.1 at `~/Library/Audio/Plug-Ins/VST3/Dexed.vst3`. Its executable is a
universal x86_64/arm64 Mach-O and has SHA-256
`0e81334bedc78883ab69822608e5f90508547ed9c24ba7f72c1f60f83106bcb2`.
Dexed is GPL-3.0; it is free/open-source software. Do not copy the locally
installed bundle or any third-party DX7 cartridge files into this repository.
The factory state used here does not reference an external sample library.

Pedalboard 0.9.24 (GPL-3.0), NumPy 2.5.2, and Python 3.14.6 were used. Reproduce
after installing Dexed VST3 1.0.1 from its upstream distribution:

```sh
brew install --cask dexed
uv venv .venv-pedalboard-qualification
uv pip install --python .venv-pedalboard-qualification/bin/python \
  -r tools/qualification/requirements-pedalboard.txt
.venv-pedalboard-qualification/bin/python \
  tools/qualification/pedalboard_instrument.py \
  --plugin "$HOME/Library/Audio/Plug-Ins/VST3/Dexed.vst3" \
  --state /tmp/llm-studio-dexed.state \
  --output /tmp/llm-studio-dexed.wav
```

Homebrew's cask metadata was checked locally and identifies this exact 1.0.1
package and <https://asb2m10.github.io/dexed/> as its project source. Both
Pedalboard and Dexed are GPL-3.0, so distribution and process/linkage boundaries
need licence review before this repository chooses its own implementation
licence. The generated audio is not assumed to inherit a software licence.

The probe loads the binary without opening its editor, captures/restores the
plugin's raw VST3 state, discovers parameter metadata, submits one complete
timestamped MIDI schedule, renders offline, verifies the result, and atomically
publishes a float WAV and JSON manifest. It never constructs an audio stream or
selects an audio device. State files are native-plugin data and must only be
restored into the pinned binary in a crash-isolated worker.

## Actual results

Two separate Python processes loaded the plugin and rendered successfully. The
second reported `restored_existing: true` and the same raw-state SHA-256,
`0f040f287d2933ef59253f5b4aea74a95c825c00759667dbd905a97da39b2c96`.
Both output files were byte-exact with SHA-256
`a11fcd0eb11bc731053537d24478808ef76bcaefd2153be3426e7c51dff6f87e`.
The observed reproducibility class is therefore **bit-exact for this factory
patch, event fixture, host, buffer size, and pinned versions**. Other patches,
random/modulated parameters, and version changes need their own tolerance.

Pedalboard identified Dexed as an instrument and exposed 158 parameters,
including stable-looking keys plus display names, values, and ranges. Raw VST3
state round-tripped without GUI interaction. Parameter identifiers are still a
version-pinned adapter concern; names alone are not promised stable.

The fixture submitted MIDI note-on/off and sustain CC64. A comparison render
without CC64 was effectively silent in the 0.85–1.15 s window, while the CC64
render had sustained signal (RMS energy ratio 8,638,643), so those messages were
honoured. Program change, bank select, pitch bend, aftertouch, per-note
expression, and arbitrary controllers were not used and are **unqualified**,
not implicitly supported.

The result was stereo 32-bit float WAV at 48,000 Hz, exactly 96,000 frames and
2.000 s. Peak was 0.132158 and RMS 0.035921. The first active sample was 12,059,
59 samples (1.229 ms) after the MIDI note-on timestamp. The last active sample
was 61,305, leaving an observed 27.188 ms release tail after CC64-off. This
latency is measured from signal threshold rather than plugin-reported latency;
store it as qualified patch evidence and confirm alignment with an impulse-like
patch before automatic compensation.

Initial load/render/state capture completed in 0.632 s; the restarted state
restore run completed in 0.815 s. `/tmp/llm-studio-dexed.wav.json` contains the
full discovered parameter snapshot and measurements. Local state, audio, and
manifests are evidence and are intentionally not committed.

## Other observations and decision

Surge XT and Vital also loaded as real VST3 instruments through Pedalboard and
exposed 775 and 903 parameters respectively. Surge attempted to create
`~/Documents/Surge XT` and emitted a non-writable-user-directory warning under
the filesystem sandbox, so it was not selected for this minimal fixture. That
is an instrument-specific asset-path qualification issue, not a Pedalboard
failure. Dexed required no such GUI or writable content setup.

DawDreamer was not installed or run. The issue explicitly limits it to the case
where a concrete Pedalboard requirement fails; none did. It is rejected as the
production backend for this gate because adding and maintaining a second native
host would not resolve an observed gap. Reopen that comparison only if a target
instrument, automation mode, or state-recall requirement fails in Pedalboard.

The selected production direction is Pedalboard, initially pinned to VST3
instrument workers on this Mac. Before production use, wrap each plugin render
in a cancellable process group with deadlines, record CPU/RAM, validate state
compatibility before assignment, qualify required controllers per patch, and
maintain a binary/state hash allow-list. This proves one free instrument and
the worker mechanics; it does not qualify every installed plugin.
