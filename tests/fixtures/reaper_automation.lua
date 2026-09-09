-- Executable contract for the real handler against a bounded fake host.
-- Native qualification is separate; this host can inject failures deterministically.
local path, handler_path = ...
local clock, revision, serial, mode, override, play = 0, 1, 0, 0, -1, 0
local points = {{0,1,0,0,false},{1,.9,0,0,false},{2,.8,5,.3,true},{3,.7,5,.2,false},{4,.6,0,0,false}}
local active, items, fail_insert, begin_count, end_count = '1', 0, false, 0, 0
local function clone(v) local out={} for i,p in ipairs(v) do out[i]={table.unpack(p)} end return out end
local saved_chunks = {}
local function chunk()
  local s='<VOLENV2\nEGUID {env}\nACT '..active..'\n'
  for _,p in ipairs(points) do s=s..'PT '..table.concat({p[1],p[2],p[3],p[4],p[5] and 1 or 0},' ')..'\n' end
  s=s..'>\n'; saved_chunks[s]=clone(points); return s
end
reaper = {
 genGuid=function() serial=serial+1; return 'id-'..serial end,
 EnumProjects=function() return 'project', path end,
 CountTracks=function() return 1 end, GetTrack=function() return 'track' end,
 GetTrackGUID=function() return '{track}' end,
 GetSetMediaTrackInfo_String=function() return true, 'Keys' end,
 GetTrackEnvelopeByChunkName=function() return 'env' end,
 CountAutomationItems=function() return items end,
 CountEnvelopePointsEx=function() return #points end,
 GetEnvelopeStateChunk=function() return true,chunk() end,
 GetSetEnvelopeInfo_String=function(_,key) return true, key=='GUID' and '{env}' or active end,
 GetEnvelopeScalingMode=function() return 0 end,
 GetEnvelopePointEx=function(_,_,i) return true,table.unpack(points[i+1]) end,
 ScaleFromEnvelopeMode=function(_,v) return v end,
 ScaleToEnvelopeMode=function(_,v) return v end,
 GetTrackAutomationMode=function() return mode end,
 GetGlobalAutomationOverride=function() return override end,
 GetSetProjectInfo=function() return 1 end,
 GetMediaTrackInfo_Value=function() return 0 end,
 GetProjectStateChangeCount=function() return revision end,
 time_precise=function() return clock end, GetPlayState=function() return play end,
 DeleteEnvelopePointEx=function(_,_,i) table.remove(points,i+1); revision=revision+1; return true end,
 InsertEnvelopePointEx=function(_,_,t,v,s,n,sel) if fail_insert then return false end; points[#points+1]={t,v,s,n,sel};revision=revision+1;return true end,
 Envelope_SortPointsEx=function() table.sort(points,function(a,b) return a[1]<b[1] end);return true end,
 SetEnvelopeStateChunk=function(_,s) points=clone(assert(saved_chunks[s]));revision=revision+1;return true end,
 Undo_BeginBlock2=function() begin_count=begin_count+1 end,
 Undo_EndBlock2=function() end_count=end_count+1;revision=revision+1 end,
 Undo_DoUndo2=function() error('global undo must never be used') end,
}
local handler=dofile(handler_path)
local id,token=handler.observe_session()
local p={session_id=id,session_token=token,track_guid='{track}',start_sec=1,end_sec=3}
local function call(op,expected)
 local result,err
 assert(handler.handle('test',{op='studio.'..op,params=p},function(_,r)result=r end,function(_,c)err=c end))
 if expected then assert(err==expected,tostring(err)..' expected '..expected);return end
 assert(result,err);return result
end
local function observe()
 local r=call('read_volume_envelope');p.fingerprint=r.fingerprint;p.envelope_guid=r.envelope_guid
 p.points={{time_sec=1,volume=.9},{time_sec=2,volume=.3},{time_sec=3,volume=.7}}
 return r
end
observe();local before=chunk();points[3][2]=.4 -- direct edit without revision notification
call('patch_volume_envelope','CONFLICT');assert(points[3][2]==.4)
observe();revision=revision+1;call('patch_volume_envelope','CONFLICT')
observe();clock=31;call('patch_volume_envelope','CONFLICT');clock=0
observe();p.start_sec=1.1;call('patch_volume_envelope','CONFLICT');p.start_sec=1
observe();p.points[1].volume=.5;call('patch_volume_envelope','BAD_REQUEST')
observe();p.envelope_guid='{other}';call('patch_volume_envelope','CONFLICT')
for _,value in ipairs({2,3,4,5}) do observe();mode=value;call('patch_volume_envelope','UNSUPPORTED');mode=0 end
observe();play=1;call('patch_volume_envelope','UNSUPPORTED');play=0
observe();override=0;call('patch_volume_envelope','UNSUPPORTED');override=-1
for value=0,5 do mode=value;p.volume=.5;call('set_mixer','UNSUPPORTED') end
mode=0;p.volume=nil
items=1;call('read_volume_envelope','UNSUPPORTED');items=0
observe();local unchanged=chunk();fail_insert=true;call('patch_volume_envelope','VERIFY_FAILED');fail_insert=false
assert(chunk()==unchanged and begin_count==end_count,'failed write must restore envelope and close undo block')
observe();before=chunk();local result=call('patch_volume_envelope');p.receipt=result.receipt
assert(points[1][2]==1 and points[5][2]==.6 and points[4][3]==5 and points[4][4]==.2,'outside and right interpolation retained')
assert(points[3][2]==.3 and points[3][3]==0)
call('patch_volume_envelope','CONFLICT') -- single use observation
assert(call('undo_volume_patch').undone);assert(chunk()==before)
call('undo_volume_patch','CONFLICT')
observe();result=call('patch_volume_envelope');p.receipt=result.receipt;revision=revision+1
unchanged=chunk();call('undo_volume_patch','CONFLICT');assert(chunk()==unchanged)
print('automation handler contract passed')
