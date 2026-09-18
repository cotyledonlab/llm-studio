-- Wait for a real producer edit, then prove an observed proposal fails closed.
local c = assert(STUDIO_HUMAN_CONFLICT)
assert(c.source:match('^/private/tmp/llm%-studio%-reaper/'))
assert(c.profile:match('^/private/tmp/llm%-studio%-reaper/'))

local report = assert(io.open(c.output, 'w'))
local finished = false
local function record(key, value)
  report:write(key .. '=' .. tostring(value) .. '\n')
  report:flush()
end
local function finish(ok, detail)
  if finished then return end
  finished = true
  record('detail', detail)
  record('human_conflict_qualification', ok and 'pass' or 'fail')
  report:close()
end

local project, path = reaper.EnumProjects(-1, '')
if path ~= c.source or reaper.GetResourcePath() ~= c.profile then
  finish(false, 'active source or profile differs')
  return
end
if reaper.GetPlayState() ~= 0 then
  finish(false, 'transport must be stopped')
  return
end

local track = reaper.GetTrack(project, 0)
local envelope = track and reaper.GetTrackEnvelopeByChunkName(track, '<VOLENV2')
if not envelope then
  finish(false, 'track 1 volume envelope missing')
  return
end
local handler = dofile(c.handler)
local session_result
handler.handle('human-session', {op='studio.session_snapshot', params={}},
  function(_, result) session_result = result end,
  function(_, code, detail) finish(false, code .. ':' .. detail) end)
if finished or not session_result then return end

local session = session_result.session
local params = {
  session_id=session.id, session_token=session.token,
  track_guid=reaper.GetTrackGUID(track), start_sec=1, end_sec=3,
}
local baseline
local baseline_chunk
local observed_at
local refreshes = 0
local function observe()
  local result, code, detail
  handler.handle('human-observe-' .. tostring(refreshes),
    {op='studio.read_volume_envelope', params=params},
    function(_, value) result = value end,
    function(_, why, message) code, detail = why, message end)
  if not result then
    finish(false, tostring(code) .. ':' .. tostring(detail))
    return false
  end
  if #result.points < 2 or result.points[1].time_sec ~= 1
      or result.points[#result.points].time_sec ~= 3 then
    finish(false, 'existing one/three-second boundaries required')
    return false
  end
  baseline = result
  local ok
  ok, baseline_chunk = reaper.GetEnvelopeStateChunk(envelope, '', false)
  if not ok then
    finish(false, 'cannot capture envelope chunk')
    return false
  end
  observed_at = reaper.time_precise()
  refreshes = refreshes + 1
  record('observation_refresh', refreshes)
  return true
end

if not observe() then return end
record('armed', true)
record('instruction', 'move the existing two-second volume point once')

local function poll()
  if finished then return end
  if reaper.EnumProjects(-1, '') ~= project or reaper.GetPlayState() ~= 0 then
    finish(false, 'session changed or transport started while armed')
    return
  end
  local ok, current_chunk = reaper.GetEnvelopeStateChunk(envelope, '', false)
  if not ok then
    finish(false, 'cannot poll envelope chunk')
    return
  end
  if current_chunk ~= baseline_chunk then
    local age = reaper.time_precise() - observed_at
    params.fingerprint = baseline.fingerprint
    params.envelope_guid = baseline.envelope_guid
    params.points = {
      {time_sec=1, volume=baseline.points[1].volume},
      {time_sec=2, volume=.25},
      {time_sec=3, volume=baseline.points[#baseline.points].volume},
    }
    local applied, error_code, error_detail
    handler.handle('human-apply', {op='studio.patch_volume_envelope', params=params},
      function() applied = true end,
      function(_, code, detail) error_code, error_detail = code, detail end)
    local _, after_chunk = reaper.GetEnvelopeStateChunk(envelope, '', false)
    local preserved = after_chunk == current_chunk
    local fresh = age <= baseline.max_age_sec
    record('observation_age_sec', string.format('%.6f', age))
    record('max_age_sec', baseline.max_age_sec)
    record('within_freshness_bound', fresh)
    record('error_code', error_code or '')
    record('error_detail', error_detail or '')
    record('proposal_applied', not not applied)
    record('producer_edit_preserved_exactly', preserved)
    if error_code == 'CONFLICT' and not applied and preserved and fresh then
      reaper.Main_SaveProjectEx(project, c.source, 0)
      record('producer_edit_saved', true)
      finish(true, 'fresh intervening human edit rejected without overwrite')
    else
      finish(false, 'human edit conflict did not meet all checks')
    end
    return
  end
  if reaper.time_precise() - observed_at >= 20 then
    if not observe() then return end
  end
  reaper.defer(poll)
end
reaper.defer(poll)
