-- Continue the native A4 probe after REAPER terminates a script on project open.
local c = assert(STUDIO_TAKE_REPLACEMENT)
assert(c.root:match('^/private/tmp/llm%-studio%-reaper/'))
local prior_file = assert(io.open(c.root .. '/native-evidence.txt', 'r'))
local prior = prior_file:read('*a')
prior_file:close()
local source_revision_before = tonumber(prior:match('source_revision_before=(%d+)'))
local source_dirty_before = tonumber(prior:match('source_dirty_before=(%d+)'))
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
  local keys, bass, drums = reaper.GetTrack(0, 0), reaper.GetTrack(0, 1), reaper.GetTrack(0, 2)
  local function name(track)
    local _, value = reaper.GetSetMediaTrackInfo_String(track, 'P_NAME', '', false)
    return value
  end
  check(name(keys) == 'Keys' and name(bass) == 'Bass' and name(drums) == 'Drums',
    'logical_parts_survive_reopen')
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
  local expected = {c.keys, c.bass, c.drums_b}
  local items = {}
  for index, track in ipairs({keys, bass, drums}) do
    check(reaper.CountTrackMediaItems(track) == 1, 'one_item_on_part_' .. index)
    local item = reaper.GetTrackMediaItem(track, 0)
    local take = reaper.GetActiveTake(item)
    local source = reaper.GetMediaItemTake_Source(take)
    local _, item_guid = reaper.GetSetMediaItemInfo_String(item, 'GUID', '', false)
    check(reaper.GetMediaSourceFileName(source, '') == expected[index]
      and reaper.GetMediaItemInfo_Value(item, 'D_POSITION') == 0
      and reaper.GetMediaItemInfo_Value(item, 'D_LENGTH') == 5
      and type(item_guid) == 'string' and item_guid ~= '',
      'durable_aligned_source_' .. index)
    items[index] = item_guid
  end
  local handler = dofile(c.handler)
  local session
  handler.handle('a4-reopen', {op='studio.session_snapshot', params={}},
    function(_, value) session = value.session end,
    function(_, code, detail) error(code .. ':' .. detail) end)
  check(session ~= nil and session.id == active_path, 'reopened_session_identity')
  local observed
  handler.handle('a4-rebind', {op='studio.read_stem', params={
    session_id=session.id, session_token=session.token,
    track_guid=reaper.GetTrackGUID(drums), item_guid=items[3]}},
    function(_, value) observed = value end,
    function(_, code, detail) error(code .. ':' .. detail) end)
  check(observed and observed.source_path == c.drums_b
    and observed.item_guid == items[3], 'drum_binding_reconciled_after_reopen')
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
