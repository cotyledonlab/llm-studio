-- Read-only REAPER sampler for Gate B. Run while the producer's playback is
-- active; it records audio/media underrun timestamps and deferred-loop delay.
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
local previous_audio, previous_media = reaper.GetUnderrunTime()
local audio_events, media_events = 0, 0
local previous_loop = reaper.time_precise()
local maximum_loop_gap_ms = 0
local interval_s = 0.1

file:write(string.format(
  '{"sample_epoch":%d,"audio_xrun_ms":0,"media_xrun_ms":0,"current_ms":0,"audio_xrun_events":0,"media_xrun_events":0,"latest_audio_xrun_epoch":null,"latest_media_xrun_epoch":null,"loop_gap_ms":0,"max_loop_gap_ms":0}\n',
  os.time()
))
file:flush()

local function json_number(value)
  if value == nil then return "null" end
  return string.format("%.6f", value)
end

local function sample()
  if reaper.GetExtState(section, stopped_key) == "1" then
    file:flush()
    file:close()
    return
  end

  local now = reaper.time_precise()
  local gap_ms = (now - previous_loop) * 1000
  if gap_ms > maximum_loop_gap_ms then maximum_loop_gap_ms = gap_ms end
  previous_loop = now

  local audio_xrun, media_xrun, current_ms = reaper.GetUnderrunTime()
  if audio_xrun ~= previous_audio and audio_xrun ~= 0 then audio_events = audio_events + 1 end
  if media_xrun ~= previous_media and media_xrun ~= 0 then media_events = media_events + 1 end
  previous_audio, previous_media = audio_xrun, media_xrun

  local audio_epoch = "null"
  if audio_xrun ~= 0 then audio_epoch = json_number(os.time() - math.max(0, current_ms - audio_xrun) / 1000) end
  local media_epoch = "null"
  if media_xrun ~= 0 then media_epoch = json_number(os.time() - math.max(0, current_ms - media_xrun) / 1000) end
  file:write(string.format(
    '{"sample_epoch":%d,"audio_xrun_ms":%d,"media_xrun_ms":%d,"current_ms":%d,"audio_xrun_events":%d,"media_xrun_events":%d,"latest_audio_xrun_epoch":%s,"latest_media_xrun_epoch":%s,"loop_gap_ms":%.3f,"max_loop_gap_ms":%.3f}\n',
    os.time(), audio_xrun, media_xrun, current_ms, audio_events, media_events,
    audio_epoch, media_epoch, gap_ms, maximum_loop_gap_ms
  ))
  file:flush()
  reaper.defer(sample)
end

reaper.defer(sample)
