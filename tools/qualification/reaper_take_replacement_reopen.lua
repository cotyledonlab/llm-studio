-- Continue the native A4 probe after REAPER terminates a script on project open.
local c = assert(STUDIO_TAKE_REPLACEMENT)
assert(c.root:match('^/private/tmp/llm%-studio%-reaper/'))
local prior_file = assert(io.open(c.root .. '/native-evidence.txt', 'r'))
local prior = prior_file:read('*a')
prior_file:close()
local source_revision_before = tonumber(prior:match('source_revision_before=(%d+)'))
local source_dirty_before = tonumber(prior:match('source_dirty_before=(%d+)'))
local function prior_value(key)
  return prior:match(key .. '=([^\n]+)')
end
local report = assert(io.open(c.root .. '/native-evidence.txt', 'a'))
local function record(key, value)
  report:write(key .. '=' .. tostring(value) .. '\n')
  report:flush()
end
local function check(value, key)
  assert(value, key)
  record(key, 'pass')
end
local original
for index = 0, 100 do
  local project, path = reaper.EnumProjects(index, '')
  if not project then break end
  if path == c.source then original = project end
end
local function run()
  local _, active_path = reaper.EnumProjects(-1, '')
  check(active_path == c.root .. '/session.RPP'
    and reaper.GetResourcePath() == c.profile and reaper.GetPlayState() == 0,
    'reopened_copy_active_in_exact_profile')
  check(original ~= nil, 'original_tab_still_open')
  check(reaper.CountTracks(0) == 3, 'three_parts_survive_reopen')
  local parts = {
    {name='Keys', key='keys', source=c.keys},
    {name='Bass', key='bass', source=c.bass},
    {name='Drums', key='drums', source=c.drums_b},
  }
  for _, part in ipairs(parts) do
    part.track_guid = prior_value(part.key .. '_track_guid')
    part.item_guid = prior_value(part.key .. '_item_guid')
    part.take_guid = prior_value(part.key .. '_take_guid')
    check(part.track_guid and part.item_guid and part.take_guid,
      'presave_' .. part.key .. '_bindings_recorded')
    for index = 0, reaper.CountTracks(0) - 1 do
      local candidate = reaper.GetTrack(0, index)
      if reaper.GetTrackGUID(candidate) == part.track_guid then
        part.track = candidate
        break
      end
    end
    check(part.track ~= nil, 'presave_' .. part.key .. '_track_guid_rebound')
    local _, name = reaper.GetSetMediaTrackInfo_String(part.track, 'P_NAME', '', false)
    check(name == part.name, 'logical_' .. part.key .. '_name_preserved')
  end
  local keys, bass, drums = parts[1].track, parts[2].track, parts[3].track
  local _, source_chunk = reaper.GetEnvelopeStateChunk(
    reaper.GetTrackEnvelopeByChunkName(reaper.GetTrack(original, 0), '<VOLENV2'), '', false)
  local _, reopened_chunk = reaper.GetEnvelopeStateChunk(
    reaper.GetTrackEnvelopeByChunkName(keys, '<VOLENV2'), '', false)
  check(source_chunk == reopened_chunk, 'producer_keys_envelope_exact_after_reopen')
  local gain = reaper.GetMediaTrackInfo_Value(bass, 'D_VOL')
  local pan = reaper.GetMediaTrackInfo_Value(bass, 'D_PAN')
  check(math.abs(gain - 0.5011872336272722) < 1e-10 and math.abs(pan + 0.2) < 1e-12,
    'bass_mix_survives_reopen')
  local _, fx_name = reaper.TrackFX_GetFXName(bass, 0, '')
  check(fx_name == 'VST: ReaEQ (Cockos)', 'bass_fx_survives_reopen')
  for _, part in ipairs(parts) do
    check(reaper.CountTrackMediaItems(part.track) == 1,
      'one_item_on_' .. part.key)
    local item
    for index = 0, reaper.CountTrackMediaItems(part.track) - 1 do
      local candidate = reaper.GetTrackMediaItem(part.track, index)
      local _, guid = reaper.GetSetMediaItemInfo_String(candidate, 'GUID', '', false)
      if guid == part.item_guid then item = candidate; break end
    end
    check(item ~= nil, 'presave_' .. part.key .. '_item_guid_rebound')
    local take = reaper.GetActiveTake(item)
    local _, take_guid = reaper.GetSetMediaItemTakeInfo_String(take, 'GUID', '', false)
    check(take_guid == part.take_guid, 'presave_' .. part.key .. '_take_guid_rebound')
    local source = reaper.GetMediaItemTake_Source(take)
    check(reaper.GetMediaSourceFileName(source, '') == part.source
      and reaper.GetMediaItemInfo_Value(item, 'D_POSITION') == 0
      and reaper.GetMediaItemInfo_Value(item, 'D_LENGTH') == 5,
      'durable_aligned_' .. part.key .. '_source')
  end
  local handler = dofile(c.handler)
  local session
  handler.handle('a4-reopen', {op='studio.session_snapshot', params={}},
    function(_, value) session = value.session end,
    function(_, code, detail) error(code .. ':' .. detail) end)
  check(session ~= nil and session.id == active_path, 'reopened_session_identity')
  for _, part in ipairs(parts) do
    local observed
    handler.handle('a4-rebind-' .. part.key, {op='studio.read_stem', params={
      session_id=session.id, session_token=session.token,
      track_guid=part.track_guid, item_guid=part.item_guid}},
      function(_, value) observed = value end,
      function(_, code, detail) error(code .. ':' .. detail) end)
    check(observed and observed.source_path == part.source
      and observed.item_guid == part.item_guid
      and observed.take_guid == part.take_guid,
      part.key .. '_binding_reconciled_after_reopen')
  end
  record('native_qualification', 'pass')
end
local ok, err = xpcall(run, debug.traceback)
if not ok then record('failure', err) end
if original then reaper.SelectProjectInstance(original) end
local _, restored_path = reaper.EnumProjects(-1, '')
record('source_tab_restored', restored_path == c.source)
record('source_dirty_after_probe', original and reaper.IsProjectDirty(original) or 'unknown')
record('source_revision_unchanged', source_revision_before and original
  and reaper.GetProjectStateChangeCount(original) == source_revision_before or 'unverified')
record('source_dirty_unchanged', source_dirty_before and original
  and reaper.IsProjectDirty(original) == source_dirty_before or 'unverified')
report:close()
