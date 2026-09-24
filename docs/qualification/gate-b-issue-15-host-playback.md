# Gate B issue #15 host playback evidence

Host-pressure monitor and playback checks were run on 2026-09-24 with REAPER 7.80.0 on macOS 26.5.2 arm64. The disposable REAPER process was PID 21565, using profile `/private/tmp/llm-studio-reaper/gate-b-playback-20260924-a/profile/resource` and project `gate-b-playback.RPP`. The project contains three audio tracks (Keys, Bass, Drums) and a 0–5 second playback loop. CoreAudio Default was selected at 48 kHz and 512 frames.

## Render worker results

The one-worker run is recorded in `/private/tmp/llm-studio-reaper/gate-b-playback-20260924-a/one-worker-results/qualification.json`. The SuperCollider `studio.drums.sc-basic-v1` fixture (PID 22407) rendered from 05:34:23.148830 to 05:34:23.728257 UTC (579 ms); `studio.bass.sc-pulse-v1` (PID 22410) rendered from 05:34:23.729719 to 05:34:24.170365 UTC (441 ms). They ran serially as requested by `max_workers=1` and both succeeded with expected fixture hashes.

The final two-worker responsiveness run is recorded in `/private/tmp/llm-studio-reaper/gate-b-playback-20260924-a/two-worker-results-4/qualification.json`. The SuperCollider `studio.drums.sc-basic-v1` fixture (PID 23028) rendered from 05:39:42.936409 to 05:39:43.490733 UTC (554 ms); `studio.bass.sc-pulse-v1` (PID 23029) rendered from 05:39:42.937509 to 05:39:43.491179 UTC (554 ms). Their intervals overlapped by about 553 ms; both succeeded with the same expected fixture hashes. Worker RSS was not sampled, so no per-worker memory figure is available. Host memory free was 45% during this short pair. There was no deliberate memory-pressure threshold crossing.

## Playback and transport responsiveness

Native readback before the final pair identified the expected project and three track GUIDs, transport playing at 1.814833 seconds, and audio/media xrun timestamps of 0. During the pair, both worker started markers existed and neither rendered marker existed when the native stop action was triggered. The stop command returned in 100.9 ms; native readback confirmed play state 0 at 2.028167 seconds. The play command returned in 77.4 ms; native readback confirmed play state 1 at 0.010 seconds. Both commands returned while the render runner was active. Probe rows at both transitions showed zero audio/media xrun timestamps and zero xrun event counts. The observed maximum REAPER defer-loop gap during this final pair was 32.568 ms.

One-worker host evidence is in `one-worker-pressure.jsonl`; final two-worker admission evidence is in `two-worker-pressure-4.jsonl`. Admission succeeded with fresh probe observations and 43–45% free host memory. A separate final probe row showed 42% free during the earlier one-worker pair. The run did not exercise low-memory admission or the xrun cooldown. No human listening check was performed. Two workers are qualified only for these two short SuperCollider fixture renders during this specific playback loop on this host.

## Cleanup and limitations

The REAPER host probe stop script was attempted once through the app command line and exited with status 134; it did not write a final `probe_running=false` row. The last JSONL row therefore still says `probe_running=true`. The exact disposable REAPER process was then verified by PID and full command line and terminated; this also terminated the deferred probe. The shared producer REAPER process was not touched. `gate-b-playback-snapshot.RPP` is a byte-identical snapshot of the disposable project. Its SHA-256 and the active disposable project's hash are both `6100c44e966035ad462b8d68d7a64fecadae96f57c87a9406adfc8785042b856`; the source fixture remains `90c44753ee58367f36f90418f968f9bebc9fa393b1876150745b886696a3cc44`.

These checks establish playback overlap, native stop/start readback, and zero observed xruns for the measured runs. They do not establish behavior during memory pressure, prolonged rendering, other audio devices, or human-perceived responsiveness. A07 reference transient calibration and REAPER import readback remain separate acceptance work.
