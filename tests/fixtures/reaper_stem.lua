-- Executable replacement contract against the real handler and a fake host.
local path, handler_path = ...
local media = path:match('^(.*)/[^/]+$') .. '/media/'
local old_path = media .. string.rep('a', 64) .. '.wav'
local new_path = media .. string.rep('b', 64) .. '.wav'
local old_source = {path=old_path, length=2}
local current_source = old_source
local revision, play, serial = 5, 0, 0
local destroyed, undo_begin, undo_end = {}, 0, 0
local corrupt_readback = false
reaper = {
  genGuid=function() serial=serial+1; return 'id-' .. serial end,
  EnumProjects=function() return 'project', path end,
  CountTracks=function() return 1 end,
  GetTrack=function() return 'track' end,
  GetTrackGUID=function() return '{track}' end,
  CountTrackMediaItems=function() return 1 end,
  GetTrackMediaItem=function() return 'item' end,
  GetSetMediaItemInfo_String=function() return true, '{item}' end,
  CountTakes=function() return 1 end,
  GetActiveTake=function() return 'take' end,
  GetMediaItemTake_Source=function() return current_source end,
  GetMediaSourceFileName=function(source)
    if corrupt_readback and source ~= old_source then return '/unexpected.wav' end
    return source.path
  end,
  GetMediaSourceLength=function(source) return source.length, false end,
  GetMediaItemInfo_Value=function(_,key) return key == 'D_POSITION' and 0 or 2 end,
  GetMediaItemTakeInfo_Value=function(_,key) return key == 'D_PLAYRATE' and 1 or 0 end,
  GetSetMediaItemTakeInfo_String=function() return true, '{take}' end,
  GetProjectStateChangeCount=function() return revision end,
  GetPlayState=function() return play end,
  PCM_Source_CreateFromFile=function(p) return {path=p, length=2} end,
  PCM_Source_Destroy=function(source) destroyed[#destroyed+1]=source end,
  SetMediaItemTake_Source=function(_,source) current_source=source; revision=revision+1; return true end,
  Undo_BeginBlock2=function() undo_begin=undo_begin+1 end,
  Undo_EndBlock2=function() undo_end=undo_end+1 end,
  Undo_DoUndo2=function() error('global Undo must not be used') end,
}
local handler = dofile(handler_path)
local id, token = handler.observe_session()
local p = {session_id=id, session_token=token, track_guid='{track}', item_guid='{item}'}
local function call(op, expected_error)
  local result, error_code
  assert(handler.handle('operation', {op='studio.' .. op, params=p},
    function(_, value) result=value end, function(_, code) error_code=code end))
  if expected_error then assert(error_code == expected_error, tostring(error_code)); return end
  assert(result, tostring(error_code))
  return result
end
p.expected = call('read_stem')
assert(p.expected.item_guid == '{item}' and p.expected.source_path == old_path)
p.stem_path = new_path
p.expected.state_change_count=4
call('replace_stem', 'CONFLICT')
assert(current_source == old_source)
p.expected.state_change_count=5
play=1; call('replace_stem', 'UNSUPPORTED'); play=0
corrupt_readback=true
call('replace_stem', 'VERIFY_FAILED')
assert(current_source == old_source and undo_begin == undo_end)
corrupt_readback=false
p.expected=call('read_stem')
local result=call('replace_stem')
assert(result.observed.source_path == new_path and result.old_source_path == old_path)
assert(result.observed.item_guid == '{item}' and result.observed.take_guid == '{take}')
assert(result.observed.position_sec == 0 and result.observed.length_sec == 2)
assert(current_source.path == new_path and destroyed[#destroyed] == old_source)
call('replace_stem', 'CONFLICT')
print('stem handler contract passed')
