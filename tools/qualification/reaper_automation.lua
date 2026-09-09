-- Native integration test; programmatic external edits are NOT human evidence.
local c = assert(STUDIO_AUTOMATION)
assert(c.root:match('^/private/tmp/llm%-studio%-reaper/'))
local report = assert(io.open(c.root .. '/native-evidence.txt','w'))
local function record(key,value) report:write(key..'='..tostring(value)..'\n'); report:flush() end
local function check(value,key) assert(value,key); record(key,'pass') end
local function write(name,text) local f=assert(io.open(c.root..'/'..name,'w'));f:write(text);f:close() end
local original,original_path=reaper.EnumProjects(-1,'')
local original_count=reaper.GetProjectStateChangeCount(original)
local scratch
local function run()
  check(original_path==c.source and reaper.GetResourcePath()==c.profile,'exact_source_and_profile')
  check(reaper.GetPlayState()==0,'source_stopped')
  record('reaper_version',reaper.GetAppVersion())
  local original_env=assert(reaper.GetTrackEnvelopeByChunkName(reaper.GetTrack(original,0),'<VOLENV2'))
  local _,source_chunk=reaper.GetEnvelopeStateChunk(original_env,'',false)
  write('source-envelope.txt',source_chunk)
  -- Save a copy without changing the source's path; only the new tab is mutated.
  reaper.Main_SaveProjectEx(original,c.root..'/session.RPP',0)
  reaper.Main_OnCommand(40859,0)
  scratch=reaper.EnumProjects(-1,'')
  check(scratch~=original,'new_disposable_tab')
  reaper.Main_openProject(c.root..'/session.RPP')
  local _,path=reaper.EnumProjects(-1,'');check(path==c.root..'/session.RPP','copy_loaded')
  local handler=dofile(c.handler)
  local serial=0
  local function call(op,p,expected)
    serial=serial+1;local result,err
    handler.handle('a3-'..serial,{op='studio.'..op,params=p},function(_,r) result=r end,function(_,code,detail) err=code;record('error_'..serial,code..':'..detail) end)
    if expected then check(err==expected,'refused_'..expected..'_'..serial);return end
    assert(result,op..':'..tostring(err));return result
  end
  local session=call('session_snapshot',{}).session
  local track=reaper.GetTrack(0,0);local guid=reaper.GetTrackGUID(track)
  local env=reaper.GetTrackEnvelopeByChunkName(track,'<VOLENV2')
  local _,copied=reaper.GetEnvelopeStateChunk(env,'',false)
  check(copied==source_chunk,'source_lane_copied_exactly')
  local p={session_id=session.id,session_token=session.token,track_guid=guid,start_sec=1,end_sec=3}
  local function observe()
    local state=call('read_volume_envelope',p)
    check(#state.points>=2 and state.points[1].time_sec==1 and state.points[#state.points].time_sec==3,'existing_boundaries')
    p.fingerprint,p.envelope_guid=state.fingerprint,state.envelope_guid
    p.points={{time_sec=1,volume=state.points[1].volume},{time_sec=2,volume=.25},{time_sec=3,volume=state.points[#state.points].volume}}
    return state
  end
  local source_mode=reaper.GetTrackAutomationMode(track)
  for mode=0,5 do
    reaper.SetTrackAutomationMode(track,mode);p.volume=.5;call('set_mixer',p,'UNSUPPORTED')
  end
  p.volume=nil;reaper.SetTrackAutomationMode(track,source_mode)
  local _,after_modes=reaper.GetEnvelopeStateChunk(env,'',false)
  check(after_modes==source_chunk,'all_static_modes_preserve_lane')
  reaper.SetTrackAutomationMode(track,1)
  local import={session_id=session.id,session_token=session.token,track_guid=guid,stem_path=c.stem,position_sec=0}
  check(call('import_stem',import).length_sec==5,'five_second_tone_imported')
  reaper.InsertTrackAtIndex(reaper.CountTracks(0),false)
  local other=reaper.GetTrack(0,reaper.CountTracks(0)-1)
  reaper.GetSetMediaTrackInfo_String(other,'P_NAME','UnrelatedControl',true)
  local _,other_before=reaper.GetTrackStateChunk(other,'',false)
  local before=observe()
  -- Native edit between observation and apply, without going through the handler.
  local ok,t,v,s,n,sel=reaper.GetEnvelopePointEx(env,-1,1);assert(ok)
  assert(reaper.SetEnvelopePointEx(env,-1,1,t,v*.8,s,n,sel,false))
  local _,edited=reaper.GetEnvelopeStateChunk(env,'',false)
  call('patch_volume_envelope',p,'CONFLICT')
  local _,kept=reaper.GetEnvelopeStateChunk(env,'',false);check(kept==edited,'intervening_edit_not_overwritten')
  assert(reaper.SetEnvelopePointEx(env,-1,1,t,v,s,n,sel,false))
  local _,baseline_chunk=reaper.GetEnvelopeStateChunk(env,'',false)
  write('baseline-envelope.txt',baseline_chunk)
  reaper.Main_SaveProjectEx(0,c.root..'/baseline.RPP',0)
  observe();local result=call('patch_volume_envelope',p)
  record('named_undo',result.undo_label)
  local _,other_after=reaper.GetTrackStateChunk(other,'',false)
  check(other_before==other_after,'unrelated_track_unchanged')
  local _,patched=reaper.GetEnvelopeStateChunk(env,'',false);write('patched-envelope.txt',patched)
  p.receipt=result.receipt
  local recovered=call('undo_volume_patch',p)
  local _,restored=reaper.GetEnvelopeStateChunk(env,'',false)
  check(recovered.undone and restored==baseline_chunk,'checked_recovery_exact')
  observe();result=call('patch_volume_envelope',p);p.receipt=result.receipt
  reaper.Main_SaveProjectEx(0,c.root..'/processed.RPP',0)
  reaper.Undo_BeginBlock2(0);reaper.SetMediaTrackInfo_Value(other,'D_PAN',.25)
  reaper.Undo_EndBlock2(0,'Simulated unrelated producer edit',-1)
  call('undo_volume_patch',p,'CONFLICT')
  check(reaper.GetMediaTrackInfo_Value(other,'D_PAN')==.25,'unrelated_edit_retained')
  reaper.Main_SaveProjectEx(0,c.root..'/session.RPP',8)
  local _,saved_chunk=reaper.GetEnvelopeStateChunk(env,'',false)
  reaper.Main_openProject(c.root..'/session.RPP')
  track=reaper.GetTrack(0,0);env=reaper.GetTrackEnvelopeByChunkName(track,'<VOLENV2')
  local _,reopened=reaper.GetEnvelopeStateChunk(env,'',false)
  check(reopened==saved_chunk,'patch_survives_reopen')
  write('reopened-envelope.txt',reopened)
  record('native_qualification','pass')
end
local ok,err=xpcall(run,debug.traceback)
if not ok then record('failure',err) end
reaper.SelectProjectInstance(original)
record('source_tab_restored',reaper.EnumProjects(-1,'')==original)
record('source_revision_unchanged',reaper.GetProjectStateChangeCount(original)==original_count)
report:close()
