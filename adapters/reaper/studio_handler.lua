-- Bounded studio semantics inside the pinned controller's serialized daemon.
-- No queues, second daemon, project opening or generic evaluation endpoint.
local M = {}
local studio_home = os.getenv('HOME') or ''
local roots = { studio_home .. '/Music/ReaperConnector/Test Projects/', '/private/tmp/llm-studio-reaper/' }
local startup = reaper.genGuid()
local identity, epoch = nil, 0

local function project_path()
  local project, path = reaper.EnumProjects(-1, '')
  return path or '', project
end

function M.observe_session()
  local path, project = project_path()
  local current = tostring(project) .. '|' .. path
  if current ~= identity then identity, epoch = current, epoch + 1 end
  return path, startup .. ':' .. tostring(epoch)
end

local function finite(value)
  return type(value) == 'number' and value == value and math.abs(value) < math.huge
end

local function shellquote(value)
  return "'" .. value:gsub("'", "'\\''") .. "'"
end

-- macOS qualification: reject lexical traversal and every symlink component.
-- The read-only shell predicate is fixed; paths are single-quoted data.
local function canonical(path)
  if type(path) ~= 'string' or path:sub(1, 1) ~= '/' or path:find('[%c]') or path:find('//', 1, true) then return false end
  local checks, prefix = {}, ''
  for part in path:gmatch('[^/]+') do
    if part == '.' or part == '..' then return false end
    prefix = prefix .. '/' .. part
    checks[#checks + 1] = '[ ! -L ' .. shellquote(prefix) .. ' ]'
  end
  local pipe = io.popen(table.concat(checks, ' && ') .. ' && printf safe', 'r')
  if not pipe then return false end
  local output = pipe:read('*a')
  local ok = pipe:close()
  return ok and output == 'safe'
end

local function disposable()
  local path = project_path()
  if not path:lower():match('%.rpp$') then return false end
  for _, root in ipairs(roots) do
    if path:sub(1, #root) == root then return canonical(path) end
  end
  return false
end

local function find_track(guid)
  for index = 0, reaper.CountTracks(0) - 1 do
    local track = reaper.GetTrack(0, index)
    if reaper.GetTrackGUID(track) == guid then return track, index end
  end
end

local function snapshot()
  local id, token = M.observe_session()
  local tracks = {}
  for index = 0, reaper.CountTracks(0) - 1 do
    local track = reaper.GetTrack(0, index)
    local _, name = reaper.GetSetMediaTrackInfo_String(track, 'P_NAME', '', false)
    tracks[#tracks + 1] = { guid = reaper.GetTrackGUID(track), name = name, index = index }
  end
  return { session = { id = id, path = id, token = token, state_change_count = reaper.GetProjectStateChangeCount(0) }, tracks = tracks }
end

function M.handle(op_id, req, reply_ok, reply_err)
  local op, p = req.op, req.params or {}
  if type(op) ~= 'string' or op:sub(1, 7) ~= 'studio.' then return false end
  local function fail(code, detail) reply_err(op_id, code, detail); return true end
  local function done(result) reply_ok(op_id, result, { 'op:' .. op, 'observed:reascript' }); return true end
  if type(p) ~= 'table' then return fail('BAD_REQUEST', 'params must be an object') end
  if op == 'studio.session_snapshot' then return done(snapshot()) end
  if op ~= 'studio.get_track_state' and op ~= 'studio.set_mixer' and op ~= 'studio.import_stem' then return fail('UNSUPPORTED', op) end
  local id, token = M.observe_session()
  if id == '' or p.session_id ~= id or p.session_token ~= token then return fail('SESSION_CHANGED', 'active loaded project differs') end
  local track, index = find_track(p.track_guid)
  if not track then return fail('TRACK_ORPHANED', 'track GUID absent') end
  if op == 'studio.get_track_state' then
    local fx = {}
    for i = 0, reaper.TrackFX_GetCount(track) - 1 do
      local _, name = reaper.TrackFX_GetFXName(track, i, '')
      fx[#fx + 1] = { index = i, name = name, params = reaper.TrackFX_GetNumParams(track, i) }
    end
    return done({ guid = p.track_guid, index = index, volume = reaper.GetMediaTrackInfo_Value(track, 'D_VOL'),
      pan = reaper.GetMediaTrackInfo_Value(track, 'D_PAN'), fx = fx })
  end
  if not disposable() then return fail('UNSAFE_PROJECT', 'writes require a canonical disposable saved project') end
  if op == 'studio.set_mixer' then
    if p.volume == nil and p.pan == nil then return fail('BAD_REQUEST', 'no controls requested') end
    if p.volume ~= nil and (not finite(p.volume) or p.volume < 0 or p.volume > 10^(12/20)) then return fail('BAD_REQUEST', 'invalid linear gain') end
    if p.pan ~= nil and (not finite(p.pan) or p.pan < -1 or p.pan > 1) then return fail('BAD_REQUEST', 'invalid pan') end
    -- Do not make a mixer write while automation can immediately override it.
    if reaper.GetTrackAutomationMode(track) ~= 0 or reaper.GetGlobalAutomationOverride() ~= -1 then return fail('UNSUPPORTED', 'requires trim/read mode with no global override') end
    reaper.Undo_BeginBlock2(0)
    if p.volume ~= nil then reaper.SetMediaTrackInfo_Value(track, 'D_VOL', p.volume) end
    if p.pan ~= nil then reaper.SetMediaTrackInfo_Value(track, 'D_PAN', p.pan) end
    reaper.Undo_EndBlock2(0, 'LLM Studio qualification mixer ' .. op_id, -1)
    return done({ observed = { volume = reaper.GetMediaTrackInfo_Value(track, 'D_VOL'), pan = reaper.GetMediaTrackInfo_Value(track, 'D_PAN') } })
  end
  local position = p.position_sec or 0
  if not finite(position) or position < 0 then return fail('BAD_REQUEST', 'invalid position') end
  local media = id:match('^(.*)/[^/]+$') .. '/media/'
  local base = type(p.stem_path) == 'string' and p.stem_path:match('([^/]+)$') or ''
  if #base ~= 68 or not base:match('^[a-f0-9]+%.wav$') or p.stem_path ~= media .. base or not canonical(p.stem_path) then return fail('UNSAFE_ASSET', 'requires staged hash-addressed session WAV') end
  local source = reaper.PCM_Source_CreateFromFile(p.stem_path)
  if not source then return fail('IMPORT_FAILED', 'cannot load staged source') end
  local length, quarter_notes = reaper.GetMediaSourceLength(source)
  if not finite(length) or length <= 0 or quarter_notes then
    reaper.PCM_Source_Destroy(source)
    return fail('IMPORT_FAILED', 'source must have positive seconds length')
  end
  reaper.Undo_BeginBlock2(0)
  local item = reaper.AddMediaItemToTrack(track)
  local take = item and reaper.AddTakeToMediaItem(item)
  if not take then
    if item then reaper.DeleteTrackMediaItem(track, item) end
    reaper.PCM_Source_Destroy(source)
    reaper.Undo_EndBlock2(0, 'LLM Studio failed import ' .. op_id, -1)
    return fail('IMPORT_FAILED', 'could not allocate item/take')
  end
  reaper.SetMediaItemTake_Source(take, source)
  reaper.SetMediaItemInfo_Value(item, 'D_POSITION', position)
  reaper.SetMediaItemInfo_Value(item, 'D_LENGTH', length)
  reaper.UpdateItemInProject(item)
  reaper.Undo_EndBlock2(0, 'LLM Studio import ' .. op_id, -1)
  local actual_source = reaper.GetMediaItemTake_Source(take)
  local path = reaper.GetMediaSourceFileName(actual_source, '')
  local _, item_guid = reaper.GetSetMediaItemInfo_String(item, 'GUID', '', false)
  return done({ durable_path = path, track_guid = reaper.GetTrackGUID(reaper.GetMediaItemTrack(item)),
    item_guid = item_guid, length_sec = reaper.GetMediaItemInfo_Value(item, 'D_LENGTH'), position_sec = reaper.GetMediaItemInfo_Value(item, 'D_POSITION') })
end

return M
