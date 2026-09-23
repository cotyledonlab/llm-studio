-- Qualify A15 with one real manual edit on a disposable project.
--
-- Invocation: open a saved disposable .RPP under /private/tmp/llm-studio-reaper/
-- in an isolated REAPER profile, stop transport, then forward a wrapper that
-- sets STUDIO_A15={project=exact_path,profile=exact_resource} before dofile(this).
-- It adds a named spare track, patches the unique Keys
-- volume envelope, and waits up to ten minutes for a clear, settled rightward
-- pan move on the spare track. It calls checked recovery once and accepts an
-- envelope-only restore with the manual pan intact, or CONFLICT with both edits
-- intact. It saves the disposable RPP after verifying either safe outcome.
-- Evidence is written beside the RPP. Source projects and prior test tabs are
-- never opened or selected by this script. Do not run it in a producer project.

local BASE = '/private/tmp/llm-studio-reaper/'
local config = assert(STUDIO_A15, 'exact project/profile config required')
assert(type(config.project) == 'string' and config.project:sub(1, #BASE) == BASE
    and config.project:lower():match('%.rpp$'), 'exact disposable project required')
assert(type(config.profile) == 'string' and config.profile:sub(1, #BASE) == BASE,
  'exact isolated resource path required')
local SPARE_NAME = 'A15 Manual Recovery Pan'
local MAX_WAIT_SEC = 600
local PAN_DELTA = 0.10
local PAN_SETTLE_SEC = 1.0
local PAN_SETTLE_POLLS = 5

local function script_path()
  local source = debug.getinfo(1, 'S').source
  assert(source:sub(1, 1) == '@', 'run this file as a ReaScript')
  return source:sub(2)
end

local script = script_path()
local handler_path = script:gsub('/tools/qualification/reaper_a15_human_recovery%.lua$',
  '/adapters/reaper/studio_handler.lua')
local handler_file = handler_path ~= script and io.open(handler_path, 'rb')
assert(handler_file, 'cannot locate adapters/reaper/studio_handler.lua from this script')
handler_file:close()

local project, project_path = reaper.EnumProjects(-1, '')
local profile = reaper.GetResourcePath()
assert(project_path == config.project, 'active project must match exact disposable target')
assert(profile == config.profile, 'REAPER resource must match exact isolated profile')
assert(reaper.GetPlayState() == 0, 'transport must be stopped')
local matching_tabs, tab_index = 0, 0
while true do
  local tab, tab_path = reaper.EnumProjects(tab_index, '')
  if not tab then break end
  if tab_path == project_path then
    matching_tabs = matching_tabs + 1
    assert(tab == project, 'target path is open in another tab')
  end
  tab_index = tab_index + 1
  assert(tab_index <= 1000, 'project tab enumeration exceeded bound')
end
assert(matching_tabs == 1, 'target project path must be unique among open tabs')

local stamp = tostring(os.time())
local report_path = project_path .. '.a15-human-recovery-' .. stamp .. '.txt'
local collision = io.open(report_path, 'rb')
local suffix = 0
while collision do
  collision:close()
  suffix = suffix + 1
  report_path = project_path .. '.a15-human-recovery-' .. stamp .. '-' .. suffix .. '.txt'
  collision = io.open(report_path, 'rb')
end
local report = assert(io.open(report_path, 'w'))
local lock_section = 'LLMStudioA15HumanRecovery'
local lock_key = project_path
local lock_owner
local finished = false
local function record(key, value)
  report:write(key .. '=' .. tostring(value) .. '\n')
  report:flush()
end
local function save_evidence(path, content)
  local file = assert(io.open(path, 'w'))
  file:write(content)
  file:close()
end
local function finish(ok, detail)
  if finished then return end
  finished = true
  if lock_owner and reaper.GetExtState(lock_section, lock_key) == lock_owner then
    reaper.DeleteExtState(lock_section, lock_key, false)
  end
  record('detail', detail)
  record('a15_human_recovery', ok and 'pass' or 'fail')
  report:close()
end

if reaper.GetExtState(lock_section, lock_key) ~= '' then
  finish(false, 'another A15 watcher is already armed for this project')
  return
end
lock_owner = stamp .. ':' .. tostring({})
reaper.SetExtState(lock_section, lock_key, lock_owner, false)
reaper.atexit(function() finish(false, 'ReaScript stopped before qualification completed') end)

local function fail(message)
  finish(false, message)
end

local ok, setup_error = xpcall(function()
  assert(reaper.EnumProjects(-1, '') == project, 'active project changed')
  record('project', project_path)
  record('profile', profile)
  record('reaper_version', reaper.GetAppVersion())

  local keys
  for index = 0, reaper.CountTracks(project) - 1 do
    local track = reaper.GetTrack(project, index)
    local _, name = reaper.GetTrackName(track, '')
    if name == 'Keys' then
      assert(not keys, 'expected exactly one track named Keys')
      keys = track
    end
  end
  assert(keys, 'track named Keys is required')
  local envelope = assert(reaper.GetTrackEnvelopeByChunkName(keys, '<VOLENV2'),
    'Keys volume envelope is required')
  local keys_guid = reaper.GetTrackGUID(keys)

  -- Add the spare track before obtaining the handler observation so this
  -- setup change is part of the proposal baseline, not the human edit.
  local track_count = reaper.CountTracks(project)
  reaper.InsertTrackAtIndex(track_count, false)
  local spare = assert(reaper.GetTrack(project, track_count), 'spare track was not created')
  reaper.GetSetMediaTrackInfo_String(spare, 'P_NAME', SPARE_NAME, true)
  reaper.SetMediaTrackInfo_Value(spare, 'D_PAN', 0)
  local _, spare_name = reaper.GetTrackName(spare, '')
  assert(spare_name == SPARE_NAME, 'spare track name readback failed')
  local spare_guid = reaper.GetTrackGUID(spare)
  local initial_pan = reaper.GetMediaTrackInfo_Value(spare, 'D_PAN')
  assert(initial_pan == 0, 'spare track must start centered')

  local handler = dofile(handler_path)
  local serial = 0
  local function call(operation, params, expected_error)
    serial = serial + 1
    local result, error_code, error_detail
    handler.handle('a15-human-' .. serial,
      {op='studio.' .. operation, params=params},
      function(_, value) result = value end,
      function(_, code, detail) error_code, error_detail = code, detail end)
    if expected_error == 'either' then
      return result, error_code, error_detail
    elseif expected_error then
      assert(not result and error_code == expected_error,
        'expected ' .. expected_error .. ', got ' .. tostring(error_code)
          .. ':' .. tostring(error_detail))
      return nil, error_code
    end
    assert(result, operation .. ' failed: ' .. tostring(error_code)
      .. ':' .. tostring(error_detail))
    return result
  end

  local session = assert(call('session_snapshot', {}).session, 'session snapshot missing')
  local params = {session_id=session.id, session_token=session.token,
    track_guid=keys_guid, start_sec=1, end_sec=3}
  local observation = call('read_volume_envelope', params)
  assert(#observation.points >= 2 and observation.points[1].time_sec == 1
      and observation.points[#observation.points].time_sec == 3,
    'Keys envelope requires existing unique one- and three-second boundaries')
  params.fingerprint = observation.fingerprint
  params.envelope_guid = observation.envelope_guid
  local midpoint_volume
  for _, candidate in ipairs({.25, .3125, .4375, .5625, .6875, .8125}) do
    local matches_existing = false
    for _, point in ipairs(observation.points) do
      if point.time_sec == 2 and math.abs(point.volume - candidate) < 1e-12 then
        matches_existing = true
        break
      end
    end
    if not matches_existing then midpoint_volume = candidate; break end
  end
  assert(midpoint_volume, 'could not choose a changed midpoint gain')
  params.points = {
    {time_sec=1, volume=observation.points[1].volume},
    {time_sec=2, volume=midpoint_volume},
    {time_sec=3, volume=observation.points[#observation.points].volume},
  }
  local _, baseline_chunk = reaper.GetEnvelopeStateChunk(envelope, '', false)
  assert(baseline_chunk, 'could not capture baseline Keys envelope')
  save_evidence(report_path .. '.baseline-envelope.txt', baseline_chunk)
  local patch = call('patch_volume_envelope', params)
  assert(type(patch.receipt) == 'string' and patch.receipt ~= '',
    'patch receipt missing')
  local patch_revision = assert(patch.observed and patch.observed.state_change_count,
    'patch revision missing')
  local _, patched_chunk = reaper.GetEnvelopeStateChunk(envelope, '', false)
  assert(patched_chunk and patched_chunk ~= baseline_chunk,
    'patch did not change the Keys envelope')
  save_evidence(report_path .. '.patched-envelope.txt', patched_chunk)
  record('keys_track_guid', keys_guid)
  record('keys_envelope_guid', observation.envelope_guid)
  record('spare_track_name', spare_name)
  record('spare_track_guid', spare_guid)
  record('spare_pan_before', string.format('%.17g', initial_pan))
  record('recovery_receipt', patch.receipt)
  record('patch_applied', true)
  record('patch_project_revision', patch_revision)
  record('watcher_timeout_sec', MAX_WAIT_SEC)
  record('pan_settle_sec', PAN_SETTLE_SEC)
  record('pan_settle_min_polls', PAN_SETTLE_POLLS)
  record('instruction', 'manually pan the named spare track clearly right, at least 0.10 from center')

  local armed_at = reaper.time_precise()
  local last_candidate_pan
  local stable_since
  local stable_samples = 0
  local safe_poll
  local function poll()
    if finished then return end
    if reaper.time_precise() - armed_at >= MAX_WAIT_SEC then
      fail('timed out waiting for the manual spare-track pan move')
      return
    end
    if reaper.GetExtState(lock_section, lock_key) ~= lock_owner then
      fail('watcher ownership was lost')
      return
    end
    if reaper.EnumProjects(-1, '') ~= project or reaper.GetPlayState() ~= 0
        or reaper.GetResourcePath() ~= profile then
      fail('project, profile, or transport changed while watcher was armed')
      return
    end
    local current_pan = reaper.GetMediaTrackInfo_Value(spare, 'D_PAN')
    local now = reaper.time_precise()
    if current_pan - initial_pan >= PAN_DELTA then
      if last_candidate_pan == nil or math.abs(current_pan - last_candidate_pan) > 1e-7 then
        last_candidate_pan = current_pan
        stable_since = now
        stable_samples = 1
      else
        stable_samples = stable_samples + 1
      end
    else
      last_candidate_pan = nil
      stable_since = nil
      stable_samples = 0
    end
    if stable_since and now - stable_since >= PAN_SETTLE_SEC
        and stable_samples >= PAN_SETTLE_POLLS
        and reaper.GetProjectStateChangeCount(project) > patch_revision then
      local pan_before = reaper.GetMediaTrackInfo_Value(spare, 'D_PAN')
      local revision_before = reaper.GetProjectStateChangeCount(project)
      local _, envelope_before = reaper.GetEnvelopeStateChunk(envelope, '', false)
      record('manual_pan_before_recovery', string.format('%.17g', pan_before))
      record('manual_pan_after', string.format('%.17g', pan_before))
      record('manual_pan_delta', string.format('%.17g', pan_before - initial_pan))
      record('project_revision_before_recovery', revision_before)
      record('envelope_before_recovery_matches_patch', envelope_before == patched_chunk)
      record('envelope_before_recovery_bytes', #envelope_before)
      record('envelope_before_recovery_state', envelope_before == patched_chunk and 'patched' or 'other')
      assert(pan_before - initial_pan >= PAN_DELTA,
        'spare pan returned below threshold before recovery')
      assert(envelope_before == patched_chunk,
        'Keys envelope changed during watcher; refusing recovery attempt')
      local recovery_result, recovery_error, recovery_detail = call('undo_volume_patch', {
        session_id=session.id, session_token=session.token, track_guid=keys_guid,
        receipt=patch.receipt, start_sec=1, end_sec=3,
      }, 'either')
      local pan_after = reaper.GetMediaTrackInfo_Value(spare, 'D_PAN')
      local revision_after = reaper.GetProjectStateChangeCount(project)
      local _, envelope_after = reaper.GetEnvelopeStateChunk(envelope, '', false)
      local pan_preserved = math.abs(pan_after - pan_before) <= 1e-7
      local patch_preserved = envelope_after == patched_chunk
      local baseline_restored = envelope_after == baseline_chunk
      record('recovery_error', recovery_error)
      record('recovery_error_detail', recovery_detail or '')
      record('recovery_undone', recovery_result and recovery_result.undone == true)
      record('manual_pan_after_recovery', string.format('%.17g', pan_after))
      record('project_revision_after_recovery', revision_after)
      record('envelope_after_recovery_matches_patch', patch_preserved)
      record('envelope_after_recovery_matches_baseline', baseline_restored)
      record('envelope_after_recovery_bytes', #envelope_after)
      record('envelope_after_recovery_state', baseline_restored and 'baseline' or
        (patch_preserved and 'patched' or 'other'))
      if envelope_after ~= patched_chunk and envelope_after ~= baseline_chunk then
        save_evidence(report_path .. '.unexpected-envelope-after-recovery.txt', envelope_after)
      end
      record('manual_pan_preserved', pan_preserved)
      local accepted_restore = recovery_result and recovery_result.undone == true
          and not recovery_error and pan_preserved and baseline_restored
      local accepted_conflict = not recovery_result and recovery_error == 'CONFLICT'
          and pan_preserved and patch_preserved
      record('accepted_outcome', accepted_restore and 'envelope_restored' or
        (accepted_conflict and 'conflict_preserved_both' or 'none'))
      assert(accepted_restore or accepted_conflict,
        'recovery neither safely restored the envelope nor refused while preserving both edits')
      -- Save only the active disposable target; this runner never saves any
      -- other open tab or switches away from the qualified project.
      reaper.Main_SaveProjectEx(project, project_path, 0)
      local file = assert(io.open(project_path, 'rb'), 'saved project is unreadable')
      local saved = file:read('*a')
      file:close()
      assert(saved and #saved > 0, 'saved project is empty')
      record('saved_project_bytes', #saved)
      record('saved_project_path', project_path)
      finish(true, 'settled human pan edit preserved; recovery safely restored the envelope or refused')
      return
    end
    reaper.defer(safe_poll)
  end
  safe_poll = function()
    local poll_ok, poll_error = xpcall(poll, debug.traceback)
    if not poll_ok then fail(poll_error) end
  end
  reaper.defer(safe_poll)
end, debug.traceback)

if not ok then fail(setup_error) end
