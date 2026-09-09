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

-- Short-lived observations are server-side comparison receipts, not write leases.
local observations, observation_order, undo_receipts = {}, {}, {}
local MAX_POINTS, MAX_CHUNK, FRESH_SECONDS = 2048, 262144, 30

local function has_automation(track, name)
  local env = reaper.GetTrackEnvelopeByChunkName(track, name)
  if not env then return false end
  local ok, active = reaper.GetSetEnvelopeInfo_String(env, 'ACTIVE', '', false)
  return not ok or active ~= '0' or reaper.CountEnvelopePointsEx(env, -1) > 0 or reaper.CountAutomationItems(env) > 0
end

local function envelope_state(track, first, last)
  local env = reaper.GetTrackEnvelopeByChunkName(track, '<VOLENV2')
  if not env then return nil, 'volume envelope absent' end
  if reaper.CountAutomationItems(env) ~= 0 then return nil, 'automation items are not qualified' end
  local count = reaper.CountEnvelopePointsEx(env, -1)
  if count > MAX_POINTS then return nil, 'envelope point limit exceeded' end
  local ok, chunk = reaper.GetEnvelopeStateChunk(env, '', false)
  if not ok or #chunk > MAX_CHUNK then return nil, 'envelope chunk unavailable or too large' end
  local got_guid, guid = reaper.GetSetEnvelopeInfo_String(env, 'GUID', '', false)
  if not got_guid or guid == '' then return nil, 'native envelope GUID unavailable' end
  local scale = reaper.GetEnvelopeScalingMode(env)
  if scale ~= 0 and scale ~= 1 then return nil, 'unknown gain scaling' end
  local points, bounded, previous = {}, {}, -math.huge
  for i = 0, count - 1 do
    local got, time, raw, shape, tension, selected = reaper.GetEnvelopePointEx(env, -1, i)
    if not got or not finite(time) or time <= previous or not finite(raw) or not finite(tension) then
      return nil, 'invalid or duplicate envelope points'
    end
    previous = time
    local volume = reaper.ScaleFromEnvelopeMode(scale, raw)
    if not finite(volume) or volume < 0 then return nil, 'invalid envelope gain' end
    local point = {time_sec=time, volume=volume, raw_value=raw, shape=shape, tension=tension, selected=selected}
    points[#points+1] = point
    if time >= first and time <= last then bounded[#bounded+1] = point end
  end
  local _, active = reaper.GetSetEnvelopeInfo_String(env, 'ACTIVE', '', false)
  local _, armed = reaper.GetSetEnvelopeInfo_String(env, 'ARM', '', false)
  local mode, override = reaper.GetTrackAutomationMode(track), reaper.GetGlobalAutomationOverride()
  local project_timebase = reaper.GetSetProjectInfo(0, 'PROJECT_TIMEBASE', 0, false)
  local track_timebase = reaper.GetMediaTrackInfo_Value(track, 'C_BEATATTACHMODE')
  local state = {envelope_guid=guid, track_guid=reaper.GetTrackGUID(track), points=bounded,
    start_sec=first, end_sec=last, time_domain='project_seconds', scaling_mode=scale,
    automation_mode=mode, global_override=override, active=active, armed=armed,
    project_timebase=project_timebase, track_timebase=track_timebase,
    state_change_count=reaper.GetProjectStateChangeCount(0), observed_at=reaper.time_precise(),
    max_age_sec=FRESH_SECONDS}
  -- Include host settings alongside the exact chunk; selection changes conflict too.
  local signature = chunk .. '\n' .. table.concat({mode, override, project_timebase, track_timebase}, ':')
  return {env=env, chunk=chunk, signature=signature, all=points, public=state}
end

local function remember(state, session_id, session_token)
  local fingerprint = reaper.genGuid()
  state.session_id, state.session_token = session_id, session_token
  observations[fingerprint] = state
  observation_order[#observation_order+1] = fingerprint
  if #observation_order > 32 then observations[table.remove(observation_order, 1)] = nil end
  state.public.fingerprint = fingerprint
  return state.public
end

local function same_observation(before, after)
  return before.signature == after.signature and before.public.state_change_count == after.public.state_change_count
end

local function automation_operation(op, p, track, id, token, op_id, done, fail)
  if not finite(p.start_sec) or not finite(p.end_sec) or p.start_sec < 0 or p.end_sec <= p.start_sec or p.end_sec - p.start_sec > 600 then
    return fail('BAD_REQUEST', 'range must be positive and at most 600 seconds')
  end
  local current, reason = envelope_state(track, p.start_sec, p.end_sec)
  if not current then return fail('UNSUPPORTED', reason) end
  if op == 'studio.read_volume_envelope' then return done(remember(current, id, token)) end
  if not disposable() then return fail('UNSAFE_PROJECT', 'writes require a canonical disposable saved project') end
  if reaper.GetPlayState() ~= 0 or (current.public.automation_mode ~= 0 and current.public.automation_mode ~= 1) or current.public.global_override ~= -1 then
    return fail('UNSUPPORTED', 'envelope writes require stopped Trim/Read or Read with no global override')
  end
  if current.public.active ~= '1' then return fail('UNSUPPORTED', 'volume envelope must already be active') end
  if op == 'studio.undo_volume_patch' then
    local receipt = type(p.receipt) == 'string' and undo_receipts[p.receipt]
    if not receipt or receipt.session_id ~= id or receipt.session_token ~= token or receipt.track_guid ~= p.track_guid or receipt.start_sec ~= p.start_sec or receipt.end_sec ~= p.end_sec then
      return fail('CONFLICT', 'unknown or invalidated undo receipt')
    end
    if not same_observation(receipt.after, current) then
      return fail('CONFLICT', 'intervening work; scoped revert refused')
    end
    undo_receipts[p.receipt] = nil
    -- A compensating envelope-only transaction avoids native undo snapshots
    -- that may predate uncommitted edits made by other scripts.
    reaper.Undo_BeginBlock2(0)
    local restored_ok = reaper.SetEnvelopeStateChunk(current.env, receipt.before.chunk, false)
    reaper.Undo_EndBlock2(0, 'LLM Studio revert volume patch ' .. p.receipt, -1)
    if not restored_ok then return fail('VERIFY_FAILED', 'scoped revert failed; inspect session') end
    local restored = envelope_state(track, p.start_sec, p.end_sec)
    if not restored or restored.signature ~= receipt.before.signature then return fail('VERIFY_FAILED', 'undo readback differs; inspect session') end
    return done({observed=remember(restored, id, token), undone=true})
  end
  local baseline = type(p.fingerprint) == 'string' and observations[p.fingerprint]
  if not baseline or baseline.session_id ~= id or baseline.session_token ~= token or baseline.public.track_guid ~= p.track_guid or baseline.public.start_sec ~= p.start_sec or baseline.public.end_sec ~= p.end_sec then
    return fail('CONFLICT', 'unknown or mismatched observation')
  end
  if reaper.time_precise() - baseline.public.observed_at > FRESH_SECONDS or not same_observation(baseline, current) then
    return fail('CONFLICT', 'stale observation; no points written')
  end
  if p.envelope_guid ~= current.public.envelope_guid then return fail('CONFLICT', 'envelope GUID changed') end
  if type(p.points) ~= 'table' or #p.points < 2 or #p.points > MAX_POINTS then return fail('BAD_REQUEST', 'bounded points required') end
  local left, right
  for _, point in ipairs(current.all) do
    if point.time_sec == p.start_sec then left = point end
    if point.time_sec == p.end_sec then right = point end
  end
  if not left or not right then return fail('UNSUPPORTED', 'range must use existing boundary points') end
  local previous, replacement = -math.huge, {}
  for i, point in ipairs(p.points) do
    if type(point) ~= 'table' or not finite(point.time_sec) or point.time_sec <= previous or point.time_sec < p.start_sec or point.time_sec > p.end_sec or not finite(point.volume) or point.volume < 0 or point.volume > 10^(12/20) then
      return fail('BAD_REQUEST', 'invalid ordered patch points')
    end
    previous = point.time_sec
    replacement[i] = {time_sec=point.time_sec, volume=point.volume,
      raw_value=reaper.ScaleToEnvelopeMode(current.public.scaling_mode, point.volume), shape=0, tension=0, selected=false}
  end
  local a, b = replacement[1], replacement[#replacement]
  local function close(x, y) return math.abs(x-y) <= 1e-12 * math.max(1, math.abs(y)) end
  if a.time_sec ~= p.start_sec or b.time_sec ~= p.end_sec or not close(a.volume,left.volume) or not close(b.volume,right.volume) then
    return fail('BAD_REQUEST', 'explicit boundary times and gains must match baseline')
  end
  -- The right point controls the segment outside the patch; preserve it exactly.
  replacement[1].raw_value, replacement[1].selected = left.raw_value, left.selected
  replacement[#replacement] = right
  local expected = {}
  for _, point in ipairs(current.all) do if point.time_sec < p.start_sec then expected[#expected+1] = point end end
  for _, point in ipairs(replacement) do expected[#expected+1] = point end
  for _, point in ipairs(current.all) do if point.time_sec > p.end_sec then expected[#expected+1] = point end end
  if #expected > MAX_POINTS then return fail('BAD_REQUEST', 'result exceeds point limit') end
  -- No defer, yield, external process or client round trip between comparison and writes.
  local final = envelope_state(track, p.start_sec, p.end_sec)
  if not final or not same_observation(current, final) then return fail('CONFLICT', 'state changed before apply') end
  observations[p.fingerprint] = nil
  local label = 'LLM Studio volume patch ' .. reaper.genGuid()
  reaper.Undo_BeginBlock2(0)
  local success, failure = xpcall(function()
    for i = #current.all, 1, -1 do
      local time = current.all[i].time_sec
      if time >= p.start_sec and time <= p.end_sec then assert(reaper.DeleteEnvelopePointEx(current.env, -1, i-1), 'delete failed') end
    end
    for _, point in ipairs(replacement) do
      assert(reaper.InsertEnvelopePointEx(current.env, -1, point.time_sec, point.raw_value, point.shape, point.tension, point.selected, true), 'insert failed')
    end
    assert(reaper.Envelope_SortPointsEx(current.env, -1), 'sort failed')
    local after = assert(envelope_state(track, p.start_sec, p.end_sec))
    assert(#after.all == #expected, 'point count differs')
    for i, point in ipairs(expected) do
      for _, key in ipairs({'time_sec','raw_value','shape','tension','selected'}) do
        assert(after.all[i][key] == point[key], 'point readback differs: ' .. key)
      end
    end
    -- Non-point envelope metadata must be byte-identical.
    local function metadata(chunk) return chunk:gsub('PT [^\n]*\n', '') end
    assert(metadata(after.chunk) == metadata(current.chunk), 'envelope metadata changed')
  end, debug.traceback)
  if not success then
    local restored = reaper.SetEnvelopeStateChunk(current.env, current.chunk, false)
    reaper.Undo_EndBlock2(0, label .. ' failed', -1)
    local after = envelope_state(track, p.start_sec, p.end_sec)
    return fail('VERIFY_FAILED', (restored and after and after.signature == current.signature and 'original envelope restored: ' or 'recovery uncertain: ') .. tostring(failure))
  end
  reaper.Undo_EndBlock2(0, label, -1)
  local after = envelope_state(track, p.start_sec, p.end_sec)
  if not after then return fail('VERIFY_FAILED', 'post-undo-block readback unavailable') end
  -- Only the most recent patch can ever be the native undo head.
  local receipt = reaper.genGuid()
  undo_receipts = {[receipt]={before=current, after=after, label=label, session_id=id, session_token=token,
    track_guid=p.track_guid, start_sec=p.start_sec, end_sec=p.end_sec}}
  return done({observed=remember(after, id, token), receipt=receipt, undo_label=label})
end

function M.handle(op_id, req, reply_ok, reply_err)
  local op, p = req.op, req.params or {}
  if type(op) ~= 'string' or op:sub(1, 7) ~= 'studio.' then return false end
  local function fail(code, detail) reply_err(op_id, code, detail); return true end
  local function done(result) reply_ok(op_id, result, { 'op:' .. op, 'observed:reascript' }); return true end
  if type(p) ~= 'table' then return fail('BAD_REQUEST', 'params must be an object') end
  if op == 'studio.session_snapshot' then return done(snapshot()) end
  local automation = op == 'studio.read_volume_envelope' or op == 'studio.patch_volume_envelope' or op == 'studio.undo_volume_patch'
  if not automation and op ~= 'studio.get_track_state' and op ~= 'studio.set_mixer' and op ~= 'studio.import_stem' then return fail('UNSUPPORTED', op) end
  local id, token = M.observe_session()
  if id == '' or p.session_id ~= id or p.session_token ~= token then return fail('SESSION_CHANGED', 'active loaded project differs') end
  local track, index = find_track(p.track_guid)
  if not track then return fail('TRACK_ORPHANED', 'track GUID absent') end
  if automation then return automation_operation(op, p, track, id, token, op_id, done, fail) end
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
    if (p.volume ~= nil and has_automation(track, '<VOLENV2')) or (p.pan ~= nil and has_automation(track, '<PANENV2')) then return fail('UNSUPPORTED', 'static control has an envelope; use a scoped proposal') end
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
