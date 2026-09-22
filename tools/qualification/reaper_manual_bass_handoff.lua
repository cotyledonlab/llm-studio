-- Select the disposable A4 copy for one producer fader edit; no control writes.
local c = assert(STUDIO_MANUAL_BASS_HANDOFF)
local report = assert(io.open(c.output, 'w'))
local function record(key, value)
  report:write(key .. '=' .. tostring(value) .. '\n')
  report:flush()
end
local function check(value, label)
  assert(value, label)
  record(label, 'pass')
end
local _, active = reaper.EnumProjects(-1, '')
check(active == c.source and reaper.GetResourcePath() == c.profile
  and reaper.GetPlayState() == 0, 'source_active_stopped_exact_profile')
local copy
for index = 0, 100 do
  local project, path = reaper.EnumProjects(index, '')
  if not project then break end
  if path == c.copy then copy = project end
end
check(copy ~= nil, 'disposable_copy_tab_found')
reaper.SelectProjectInstance(copy)
local _, selected = reaper.EnumProjects(-1, '')
check(selected == c.copy and reaper.CountTracks(0) == 3, 'copy_selected')
local bass = reaper.GetTrack(0, 1)
local _, name = reaper.GetSetMediaTrackInfo_String(bass, 'P_NAME', '', false)
check(name == 'Bass', 'bass_track_identified')
record('bass_gain_before', reaper.GetMediaTrackInfo_Value(bass, 'D_VOL'))
record('bass_pan_before', reaper.GetMediaTrackInfo_Value(bass, 'D_PAN'))
record('copy_path', selected)
record('ready_for_producer', true)
report:close()
