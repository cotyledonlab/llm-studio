-- Prove REAPER envelope point attachment across tempo changes on a saved copy.
local c = assert(STUDIO_AUTOMATION_TIMEBASE)
assert(c.root:match('^/private/tmp/llm%-studio%-reaper/'))
local report = assert(io.open(c.root .. '/' .. c.name .. '.txt', 'w'))
local function record(key, value) report:write(key .. '=' .. tostring(value) .. '\n'); report:flush() end
local function close(a, b) return math.abs(a - b) < 0.000001 end
local function check(value, key) assert(value, key); record(key, 'pass') end
local original, original_path = reaper.EnumProjects(-1, '')
local function read(path)
  local file = assert(io.open(path, 'rb')); local value = file:read('*a'); file:close(); return value
end
local function write(path, value)
  local file = assert(io.open(path, 'wb')); file:write(value); file:close()
end
local function run()
  check(original_path == c.source and reaper.GetResourcePath() == c.profile, 'exact_source_and_profile')
  check(reaper.GetPlayState() == 0, 'source_stopped')
  record('reaper_version', reaper.GetAppVersion())
  local changed, count = read(c.source):gsub('(TIMELOCKMODE%s+)[^\r\n]+', '%1' .. c.project, 1)
  assert(count == 1, 'source project lacks one TIMELOCKMODE')
  local copy = c.root .. '/' .. c.name .. '.RPP'; write(copy, changed)
  reaper.Main_OnCommand(40859, 0)
  local scratch = reaper.EnumProjects(-1, '')
  check(scratch ~= original, 'new_disposable_tab')
  local handler = dofile(c.handler)
  local track
  local function observe()
    local snapshot
    handler.handle('timebase-session', {op='studio.session_snapshot', params={}},
      function(_, value) snapshot = value end, function(_, code, detail) error(code .. ':' .. detail) end)
    local result
    handler.handle('timebase-read', {op='studio.read_volume_envelope', params={
      session_id=snapshot.session.id, session_token=snapshot.session.token,
      track_guid=reaper.GetTrackGUID(track), start_sec=0, end_sec=8}},
      function(_, value) result = value end, function(_, code, detail) error(code .. ':' .. detail) end)
    return assert(result)
  end
    reaper.Main_openProject(copy)
    local _, path = reaper.EnumProjects(-1, ''); assert(path == copy, c.name .. '_copy_loaded')
    track = assert(reaper.GetTrack(0, 0))
    local env = assert(reaper.GetTrackEnvelopeByChunkName(track, '<VOLENV2'))
    reaper.SetCurrentBPM(0, 120, true)
    reaper.SetMediaTrackInfo_Value(track, 'C_BEATATTACHMODE', c.track)
    local before = observe()
    record(c.name .. '_observed_timebase', table.concat({
      before.project_timebase, before.track_timebase, before.effective_timebase,
      before.attachment_domain}, ','))
    check(before.project_timebase == c.project and before.track_timebase == c.track
      and before.effective_timebase == c.effective, c.name .. '_reported_timebase')
    check(before.attachment_domain == (c.effective == 0 and 'project_time' or 'project_beats'), c.name .. '_reported_attachment')
    local got, before_sec = reaper.GetEnvelopePointEx(env, -1, 2)
    assert(got and close(before_sec, 2), c.name .. '_initial_point')
    reaper.SetCurrentBPM(0, 60, true)
    local after = observe()
    local got_after, after_sec = reaper.GetEnvelopePointEx(env, -1, 2)
    assert(got_after)
    local after_qn = reaper.TimeMap2_timeToQN(0, after_sec)
    check(close(after_sec, c.after_sec) and close(after_qn, c.after_qn), c.name .. '_tempo_behavior')
    local matched = false
    for _, point in ipairs(after.points) do
      if close(point.time_sec, after_sec) and close(point.quarter_note, after_qn) then matched = true end
    end
    check(matched, c.name .. '_adapter_positions')
  record('case_qualification', 'pass')
end
local ok, detail = xpcall(run, debug.traceback)
if not ok then record('failure', detail); record('case_qualification', 'fail') end
reaper.SelectProjectInstance(original)
record('source_tab_restored', reaper.EnumProjects(-1, '') == original)
report:close()
