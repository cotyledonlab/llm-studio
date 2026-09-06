-- Run only through the companion Python runner, with explicit disposable paths.
-- Exercises the real handler API; does not replace the installed bridge.
local config = assert(STUDIO_QUAL, 'qualification config missing')
assert(config.root:match('^/private/tmp/llm%-studio%-reaper/'), 'scratch root required')
local original, original_path = reaper.EnumProjects(-1, '')
local original_count = reaper.GetProjectStateChangeCount(original)
local report = assert(io.open(config.root .. '/handler-evidence.txt', 'w'))
local scratch = nil
local function record(key, value) report:write(key .. '=' .. tostring(value) .. '\n'); report:flush() end
local function check(condition, detail) assert(condition, detail); record(detail, 'pass') end
local function run()
  check(reaper.GetPlayState() == 0, 'producer_transport_stopped')
  local handler = dofile(config.handler)
  reaper.Main_OnCommand(40859, 0) -- File: New project tab
  scratch = reaper.EnumProjects(-1, '')
  check(scratch ~= original and reaper.CountTracks(scratch) == 0, 'new_disposable_tab')
  reaper.Main_SaveProjectEx(scratch, config.root .. '/session.RPP', 8)
  local _, saved = reaper.EnumProjects(-1, '')
  check(saved == config.root .. '/session.RPP', 'saved_disposable_identity')
  for i = 0, 1 do
    reaper.InsertTrackAtIndex(i, false)
    reaper.GetSetMediaTrackInfo_String(reaper.GetTrack(scratch, i), 'P_NAME', 'StudioTest' .. i, true)
  end
  local first, second = reaper.GetTrack(scratch, 0), reaper.GetTrack(scratch, 1)
  local first_guid, second_guid = reaper.GetTrackGUID(first), reaper.GetTrackGUID(second)
  local serial = 0
  local function call(op, params, expected_error)
    serial = serial + 1
    local result, error_code
    local handled = handler.handle('qual-' .. serial, {op = op, params = params},
      function(_, value) result = value end,
      function(_, code, detail) error_code = code; record('error_' .. serial, code .. ':' .. detail) end)
    check(handled, 'handled_' .. serial)
    if expected_error then check(error_code == expected_error, 'expected_' .. expected_error); return end
    assert(not error_code and result, op .. ' failed: ' .. tostring(error_code))
    return result
  end
  local state = call('studio.session_snapshot', {})
  check(#state.tracks == 2 and state.tracks[1].guid == first_guid and state.tracks[2].guid == second_guid, 'two_native_GUIDs')
  local function params(guid)
    return {session_id = state.session.id, session_token = state.session.token, track_guid = guid}
  end
  local p = params(first_guid)
  p.stem_path, p.position_sec = config.stem, 0
  local imported = call('studio.import_stem', p)
  check(imported.durable_path == config.stem and imported.length_sec == 1 and imported.position_sec == 0 and imported.track_guid == first_guid and imported.item_guid ~= '', 'durable_import_observed')
  -- This native API edit simulates an external fader edit; it is NOT human evidence.
  reaper.SetMediaTrackInfo_Value(first, 'D_VOL', .75)
  check(call('studio.get_track_state', params(first_guid)).volume == .75, 'external_gain_readback')
  local mix = params(first_guid); mix.volume, mix.pan = 1, 0
  call('studio.set_mixer', mix)
  reaper.Main_SaveProjectEx(scratch, config.root .. '/baseline.RPP', 0)
  state = call('studio.session_snapshot', {})
  mix = params(first_guid); mix.volume, mix.pan = .5, 1
  local changed = call('studio.set_mixer', mix)
  check(changed.observed.volume == .5 and changed.observed.pan == 1, 'gain_pan_observed')
  reaper.Main_SaveProjectEx(scratch, config.root .. '/processed.RPP', 0)
  state = call('studio.session_snapshot', {})
  reaper.GetSetMediaTrackInfo_String(first, 'P_NAME', 'Renamed', true)
  reaper.SetOnlyTrackSelected(first)
  reaper.ReorderSelectedTracks(2, 0)
  local moved = call('studio.get_track_state', params(first_guid))
  check(moved.guid == first_guid and moved.index == 1 and moved.volume == .5, 'rename_reorder_binding')
  reaper.DeleteTrack(second)
  call('studio.get_track_state', params(second_guid), 'TRACK_ORPHANED')
  local old_params = params(first_guid); old_params.volume = 1
  reaper.SelectProjectInstance(original)
  handler.observe_session()
  call('studio.set_mixer', old_params, 'SESSION_CHANGED')
  reaper.SelectProjectInstance(scratch)
  handler.observe_session()
  call('studio.set_mixer', old_params, 'SESSION_CHANGED')
  reaper.Main_SaveProjectEx(scratch, config.root .. '/final.RPP', 0)
  record('handler_qualification', 'pass')
end
local ok, error = xpcall(run, debug.traceback)
if not ok then record('failure', error) end
-- Leave disposable tabs available for inspection; never close a producer tab.
reaper.SelectProjectInstance(original)
record('producer_project_restored', reaper.EnumProjects(-1, '') == original)
record('producer_state_unchanged', reaper.GetProjectStateChangeCount(original) == original_count)
report:close()
