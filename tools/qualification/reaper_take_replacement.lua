-- Native A4 probe: all writes are to a copied disposable tab.
local c = assert(STUDIO_TAKE_REPLACEMENT)
assert(c.root:match('^/private/tmp/llm%-studio%-reaper/'))
local report = assert(io.open(c.root .. '/native-evidence.txt', 'w'))
local function record(key, value)
  report:write(key .. '=' .. tostring(value) .. '\n')
  report:flush()
end
local function check(value, key)
  assert(value, key)
  record(key, 'pass')
end
local original, original_path = reaper.EnumProjects(-1, '')
local original_revision = reaper.GetProjectStateChangeCount(original)
local original_dirty = reaper.IsProjectDirty(original)
local opening_copy = false
local function run()
  check(original_path == c.source and reaper.GetResourcePath() == c.profile,
    'exact_source_and_profile')
  check(reaper.GetPlayState() == 0, 'source_stopped')
  record('reaper_version', reaper.GetAppVersion())
  record('source_revision_before', original_revision)
  record('source_dirty_before', original_dirty)
  local source_keys = assert(reaper.GetTrack(original, 0))
  local source_env = assert(reaper.GetTrackEnvelopeByChunkName(source_keys, '<VOLENV2'))
  local _, manual_chunk = reaper.GetEnvelopeStateChunk(source_env, '', false)
  check(manual_chunk:find('PT 2 ', 1, true) ~= nil, 'producer_keys_lane_present')

  reaper.Main_SaveProjectEx(original, c.root .. '/session.RPP', 0)
  reaper.Main_OnCommand(40859, 0)
  local scratch = reaper.EnumProjects(-1, '')
  check(scratch ~= original, 'new_disposable_tab')
  reaper.Main_openProject(c.root .. '/session.RPP')
  local _, path = reaper.EnumProjects(-1, '')
  check(path == c.root .. '/session.RPP', 'copy_loaded')

  local keys = assert(reaper.GetTrack(0, 0))
  reaper.GetSetMediaTrackInfo_String(keys, 'P_NAME', 'Keys', true)
  local keys_env = assert(reaper.GetTrackEnvelopeByChunkName(keys, '<VOLENV2'))
  local _, copied_chunk = reaper.GetEnvelopeStateChunk(keys_env, '', false)
  check(copied_chunk == manual_chunk, 'manual_keys_lane_copied_exactly')
  reaper.InsertTrackAtIndex(1, false)
  reaper.InsertTrackAtIndex(2, false)
  local bass, drums = reaper.GetTrack(0, 1), reaper.GetTrack(0, 2)
  reaper.GetSetMediaTrackInfo_String(bass, 'P_NAME', 'Bass', true)
  reaper.GetSetMediaTrackInfo_String(drums, 'P_NAME', 'Drums', true)
  reaper.SetMediaTrackInfo_Value(bass, 'D_VOL', 0.5011872336272722)
  reaper.SetMediaTrackInfo_Value(bass, 'D_PAN', -0.2)
  local fx_index = reaper.TrackFX_AddByName(bass, 'ReaEQ (Cockos)', false, 1)
  check(fx_index >= 0, 'bass_fx_loaded')

  local handler = dofile(c.handler)
  local serial = 0
  local function call(op, params, expected)
    serial = serial + 1
    local result, code, detail
    handler.handle('a4-' .. serial, {op='studio.' .. op, params=params},
      function(_, value) result = value end,
      function(_, why, message) code, detail = why, message end)
    if expected then check(code == expected, 'refused_' .. expected .. '_' .. serial); return end
    assert(result, op .. ':' .. tostring(code) .. ':' .. tostring(detail))
    return result
  end
  local session = call('session_snapshot', {}).session
  local function import(track, stem)
    return call('import_stem', {session_id=session.id, session_token=session.token,
      track_guid=reaper.GetTrackGUID(track), stem_path=stem, position_sec=0})
  end
  local keys_item = import(keys, c.keys)
  local bass_item = import(bass, c.bass)
  local drum_item = import(drums, c.drums_a)
  check(keys_item.length_sec == 5 and bass_item.length_sec == 5
    and drum_item.length_sec == 5, 'aligned_five_second_items')
  local _, keys_before = reaper.GetTrackStateChunk(keys, '', false)
  local _, bass_before = reaper.GetTrackStateChunk(bass, '', false)
  local params = {session_id=session.id, session_token=session.token,
    track_guid=reaper.GetTrackGUID(drums), item_guid=drum_item.item_guid}
  local before = call('read_stem', params)
  params.expected, params.stem_path = before, c.drums_b
  local replaced = call('replace_stem', params)
  check(replaced.old_source_path == c.drums_a
    and replaced.observed.source_path == c.drums_b
    and replaced.observed.item_guid == before.item_guid
    and replaced.observed.take_guid == before.take_guid,
    'drum_source_replaced_without_rebinding')
  call('replace_stem', params, 'CONFLICT')
  local _, keys_after = reaper.GetTrackStateChunk(keys, '', false)
  local _, bass_after = reaper.GetTrackStateChunk(bass, '', false)
  check(keys_after == keys_before and bass_after == bass_before,
    'other_tracks_exactly_preserved')
  local _, keys_env_after = reaper.GetEnvelopeStateChunk(keys_env, '', false)
  check(keys_env_after == manual_chunk, 'manual_keys_lane_preserved')
  record('bass_gain', reaper.GetMediaTrackInfo_Value(bass, 'D_VOL'))
  record('bass_pan', reaper.GetMediaTrackInfo_Value(bass, 'D_PAN'))
  local _, bass_fx_name = reaper.TrackFX_GetFXName(bass, fx_index, '')
  record('bass_fx', bass_fx_name)
  reaper.Main_SaveProjectEx(0, c.root .. '/session.RPP', 0)
  local _, saved_path = reaper.EnumProjects(-1, '')
  check(saved_path == c.root .. '/session.RPP', 'copy_saved')
  record('native_stage1', 'pass')
  opening_copy = true
  -- REAPER ends a running ReaScript here. A second script verifies the reopened
  -- tab and restores the original; do not assume this call returns.
  reaper.Main_openProject(c.root .. '/session.RPP')
end
local ok, err = xpcall(run, debug.traceback)
if not ok then record('failure', err) end
if not opening_copy then
  reaper.SelectProjectInstance(original)
  record('source_tab_restored', reaper.EnumProjects(-1, '') == original)
end
report:close()
