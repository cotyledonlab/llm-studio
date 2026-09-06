# REAPER producer qualification — issue #9

This handoff qualifies the installed clean-profile bridge, OSC, restart,
adapter readback, manual fader movement, and human listening. Use only a
disposable project saved under `/private/tmp/llm-studio-reaper/` or
`~/Music/ReaperConnector/Test Projects/`. The agent never operates the REAPER
GUI. The producer performs the save/quit and any required script/fader/listen
actions.

## Prepare and install a clean profile

```sh
cd /Users/johnmaher/code/llm-studio
export CONTROLLER=/Users/johnmaher/code/reaper-controller
export CONTROLLER_PY=$CONTROLLER/.venv/bin/python
export RESOURCE=/private/tmp/llm-studio-reaper/resume-20260906/clean-profile
export PLAN=/private/tmp/llm-studio-reaper/resume-20260906/clean-plan.json
export RECEIPT=/private/tmp/llm-studio-reaper/resume-20260906/clean-receipt.json
git -C "$CONTROLLER" status --short --branch
test "$(git -C "$CONTROLLER" rev-parse HEAD)" = fd56d0008ffa5fba25cc58a70e5ae632c80b4c16
mkdir -p "$RESOURCE"
PYTHONPATH=src python3 -m llm_studio bootstrap-plan --resource "$RESOURCE" \
  --controller "$CONTROLLER" --output "$PLAN"
```

Review the plan's hashes and paths. Regenerate it if the temporary directory
has expired or the controller checkout changes. Planning writes only the local plan file.

The producer quits every REAPER instance and confirms it is stopped. Apply is
guarded and refuses a running or uncertain process; never bypass that guard.

```sh
PYTHONPATH=src python3 -m llm_studio bootstrap-apply "$PLAN" --receipt "$RECEIPT"
PYTHONPATH=src python3 -m llm_studio bootstrap-verify "$RECEIPT"
```

`verify ok:true` proves file hashes and directories, while
`runtime_verification_required:true` remains expected. If recovery is needed,
use the reported backup directory's `result.json` with
`bootstrap-rollback`, only while REAPER is stopped. Preserve the receipt and
backup directory as evidence.

## Start and prove the installed bridge

The installed 7.79 binary supports an alternate resource file. Start the isolated instance with the prepared disposable project:

```sh
/Applications/REAPER.app/Contents/MacOS/REAPER \
  -cfgfile "$RESOURCE/reaper.ini" -newinst \
  "/private/tmp/llm-studio-reaper/resume-20260906/adapter-session.RPP" \
  "$RESOURCE/Scripts/agent_bridge.lua"
```

If `adapter-session.RPP` expired, recreate it first with the pinned controller
`create <that-path> --template song`; file preparation alone is not live FX
evidence. Ensure this is the only REAPER instance before OSC or restart.

This exact script-launch form is documented by the binary but remains runtime
qualification evidence to obtain. If the instance opens without loading the
script, the producer may load/run that profile's
`Scripts/agent_bridge.lua` through Actions. Record which path was used.

Every controller command below must select the clean queue explicitly:

```sh
export REAPER_RESOURCE_PATH="$RESOURCE"
"$CONTROLLER_PY" -m reaper_connector doctor --json
"$CONTROLLER_PY" -m reaper_connector status
"$CONTROLLER_PY" -m reaper_connector bridge-send ping --timeout 10
"$CONTROLLER_PY" -m reaper_connector bridge-send hello --timeout 10
"$CONTROLLER_PY" -m reaper_connector bridge-send studio.session_snapshot --params '{}' --timeout 10
```

Accept only successful `ping`, `hello`, and `studio.session_snapshot`
whose saved path is the disposable project and whose token/GUID list is
nonempty. `UNKNOWN_OP` means the old bridge is still loaded. Port `used`
is occupancy, not proof of OSC health.

For OSC, start telemetry before sending the message so the capture overlaps
the event:

```sh
REAPER_RESOURCE_PATH="$RESOURCE" "$CONTROLLER_PY" -m reaper_connector telemetry --secs 5 --filter /time/str,/track/1/vu > /tmp/llm-studio-osc.json &
telemetry_pid=$!
sleep 0.2
REAPER_RESOURCE_PATH="$RESOURCE" "$CONTROLLER_PY" -m reaper_connector osc-send /play
sleep 3
REAPER_RESOURCE_PATH="$RESOURCE" "$CONTROLLER_PY" -m reaper_connector osc-send /stop
wait "$telemetry_pid"
cat /tmp/llm-studio-osc.json
```

The producer confirms the transport moved and stopped. The telemetry must
show transport/VU activity during playback. OSC tracks are 1-based; bridge
tracks are 0-based. Do not use OSC volume as exact fader evidence: it is a
taper and volume sends are not echoed.

## Restart and installed adapter discovery

With transport stopped, shut down the daemon, wait for its heartbeat to go
stale, then have the producer run the same script again. Do not run a second
copy before shutdown. The bridge scans at roughly 10 Hz; after the successful
shutdown reply, wait at least 16 seconds before checking the stale heartbeat.

```sh
REAPER_RESOURCE_PATH="$RESOURCE" "$CONTROLLER_PY" -m reaper_connector bridge-send bridge.shutdown --timeout 10
sleep 16
REAPER_RESOURCE_PATH="$RESOURCE" "$CONTROLLER_PY" -m reaper_connector status
```

The producer re-runs `agent_bridge.lua` in the isolated instance, or uses the
qualified command below against that instance only:

```sh
/Applications/REAPER.app/Contents/MacOS/REAPER -nonewinst -noactivate \
  "$RESOURCE/Scripts/agent_bridge.lua"
```

After the heartbeat is fresh, capture a new snapshot. Do not reuse the old
token for writes.

```sh
export REAPER_RESOURCE_PATH="$RESOURCE"
"$CONTROLLER_PY" -m reaper_connector status
"$CONTROLLER_PY" -m reaper_connector bridge-send ping --timeout 10
"$CONTROLLER_PY" -m reaper_connector bridge-send studio.session_snapshot --params '{}' --timeout 10
```

Run the read-only installed adapter probe after restart. It validates the
Python controller source and observes every track. Omit `--manual-fader` for
a single noninteractive snapshot; with it, the terminal waits for the producer
to move a fader and press Enter:

```sh
PYTHONPATH=src REAPER_RESOURCE_PATH="$RESOURCE" "$CONTROLLER_PY" \
  tools/qualification/reaper_adapter_probe.py --controller "$CONTROLLER" \
  --resource "$RESOURCE" --manual-fader \
  --output /private/tmp/llm-studio-reaper/resume-20260906/adapter-probe.json
```

Require `manual_fader.change_observed:true`, a nonempty `fx` entry in one
track state, and a successful post-restart session/token in the JSON. A
programmatic edit, screenshot, or requested value without readback does not
count as manual-fader evidence.

For Python adapter write evidence, retain a fresh `observe_session()` result,
check its path is exactly the disposable fixture, and bind its track by GUID.
Read and save the original mixer values with `read_track` before calling
`set_mixer(session, guid, gain_db=-3.0, pan=0.25)`. Record the returned
observed values, then restore the saved gain/pan (use `silent=True` if the
original volume was zero) and read back again. A timeout requires
reconciliation; do not blindly repeat a write.

Full import qualification remains a separate required step: call
`import_stem(session, guid, Path("/absolute/disposable/source.wav"))` with a
known valid WAV and retain its returned durable source path, item GUID,
position and length. The adapter stages the content-addressed asset. The
read-only probe and mixer check alone do not qualify import.

## Listening and final record

The producer listens to the non-silent disposable item on the actual
headphones/speakers while playback runs, then stops it. Capture supporting
telemetry with the same `REAPER_RESOURCE_PATH` command above and record the
producer's direct statement, monitoring path, and timestamp. RMS/peak data or
a successful render can support audibility, but cannot stand in for human
listening or prove a particular gain/pan judgement. Ask the producer to
compare the baseline and processed audio specifically for the requested
level/pan change. The prior native run’s `baseline.wav` and `processed.wav`
remain at `/private/tmp/llm-studio-reaper/qualification-6sk64bx9/`; distinguish
that native-handler comparison from the new installed-adapter evidence.

Retain plan/receipt hashes, bridge replies, fresh snapshot/token, probe JSON,
FX name/count, fader before/after, telemetry, and the producer's listening
note outside git as qualification evidence. Do not commit private audio,
credentials, plugins, or generated WAVs.

This evidence does not establish envelope conflict semantics, a production
write lease, or detection of a switch away and back between callbacks. Purchase
and licence activation remain producer actions. Keep issue #9 open until the
installed transport, restart, FX discovery, manual fader readback, and human
listening evidence are all present.
