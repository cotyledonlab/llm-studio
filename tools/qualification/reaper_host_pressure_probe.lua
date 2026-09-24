-- Read-only REAPER sampler for Gate B. Run while the producer's playback is
-- active; it records last audio/media underrun timestamps and deferred-loop delay.
-- Stop by running reaper_host_pressure_probe_stop.lua.

local section = "LLMStudioHostPressure"
local stopped_key = "stop"
local probe_path = reaper.GetResourcePath() .. "/llm-studio-host-pressure.jsonl"
local file = io.open(probe_path, "a")
if not file then
  reaper.ShowConsoleMsg("LLM Studio host-pressure probe could not open " .. probe_path .. "\n")
  return
end

reaper.SetExtState(section, stopped_key, "0", false)
local previous_audio, previous_media, previous_current_ms = reaper.GetUnderrunTime()
local audio_events, media_events = 0, 0
local previous_loop = reaper.time_precise()
local maximum_loop_gap_ms = 0
local interval_s = 0.1
local previous_audio_age_ms = nil

file:write(string.format(
  '{"sample_epoch":%d,"probe_running":true,"audio_xrun_ms":0,"media_xrun_ms":0,"current_ms":0,"audio_xrun_events":0,"media_xrun_events":0,"latest_audio_xrun_age_ms":null,"loop_gap_ms":0,"max_loop_gap_ms":0}\n',
  os.time()
))
file:flush()

local function sample()
  if reaper.GetExtState(section, stopped_key) == "1" then
    local audio_xrun, media_xrun, current_ms = reaper.GetUnderrunTime()
    file:write(string.format(
      '{"sample_epoch":%d,"probe_running":false,"audio_xrun_ms":%d,"media_xrun_ms":%d,"current_ms":%d,"audio_xrun_events":%d,"media_xrun_events":%d,"latest_audio_xrun_age_ms":null,"loop_gap_ms":0,"max_loop_gap_ms":%.3f}\n',
      os.time(), audio_xrun, media_xrun, current_ms, audio_events, media_events, maximum_loop_gap_ms
    ))
    file:flush()
    file:close()
    return
  end

  local now = reaper.time_precise()
  local gap_ms = (now - previous_loop) * 1000
  if gap_ms > maximum_loop_gap_ms then maximum_loop_gap_ms = gap_ms end
  previous_loop = now

  local audio_xrun, media_xrun, current_ms = reaper.GetUnderrunTime()
  local audio_stamp_changed = audio_xrun ~= previous_audio
  if audio_stamp_changed and audio_xrun ~= 0 then audio_events = audio_events + 1 end
  if media_xrun ~= previous_media and media_xrun ~= 0 then media_events = media_events + 1 end

  -- REAPER documents these as last-event timestamps plus current time, all
  -- in unsigned milliseconds. Modulo handles clock wrap; accumulating the
  -- delta while the timestamp stays fixed prevents an old event from becoming
  -- recent again after a full uint32 millisecond cycle.
  local audio_age = "null"
  local audio_age_value = nil
  if audio_xrun ~= 0 then
    if audio_stamp_changed or previous_audio_age_ms == nil then
      audio_age_value = (current_ms - audio_xrun) % 4294967296
    else
      audio_age_value = previous_audio_age_ms + (current_ms - previous_current_ms) % 4294967296
    end
    audio_age = tostring(audio_age_value)
  end
  file:write(string.format(
    '{"sample_epoch":%d,"probe_running":true,"audio_xrun_ms":%d,"media_xrun_ms":%d,"current_ms":%d,"audio_xrun_events":%d,"media_xrun_events":%d,"latest_audio_xrun_age_ms":%s,"loop_gap_ms":%.3f,"max_loop_gap_ms":%.3f}\n',
    os.time(), audio_xrun, media_xrun, current_ms, audio_events, media_events,
    audio_age, gap_ms, maximum_loop_gap_ms
  ))
  file:flush()
  previous_audio, previous_media = audio_xrun, media_xrun
  previous_current_ms, previous_audio_age_ms = current_ms, audio_age_value
  reaper.defer(sample)
end

reaper.defer(sample)
