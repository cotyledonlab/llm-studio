-- Stage an identical saved project in a new tab without closing any tab.
-- Main_openProject ends this ReaScript; the runner performs readback, then
-- invokes this script again in verify mode.
local c = assert(dofile(reaper.GetResourcePath()
  .. '/Scripts/llm_studio_a01_reopen_config.lua'))
assert(c.source_path:match('^/private/tmp/llm%-studio%-reaper/'))
assert(c.reopened_path:match('^/private/tmp/llm%-studio%-reaper/'))
assert(c.inventory_path:match('^/private/tmp/llm%-studio%-reaper/'))
assert(c.marker_path:match('^/private/tmp/llm%-studio%-reaper/'))
assert(c.registered_action_id:match('^RS[0-9a-f]+$'))

local function active_path()
  local _, path = reaper.EnumProjects(-1, '')
  return path
end

if c.phase == 'identify' then
  local _, _, section, command_id = reaper.get_action_context()
  assert(section == 0, 'A01 helper must be registered in the main action section')
  assert(type(command_id) == 'number' and command_id > 0,
    'REAPER did not return a positive native command ID for this action')
  local marker = assert(io.open(c.marker_path, 'w'))
  marker:write('ok=true\nregistered_action_id=', c.registered_action_id,
    '\nreaper_command_id=', tostring(math.floor(command_id)), '\n')
  marker:flush()
  marker:close()
  return
end

local function rows()
  local result, index = {}, 0
  while true do
    local project, path = reaper.EnumProjects(index, '')
    if not project then break end
    result[#result + 1] = path .. '\t'
      .. tostring(reaper.IsProjectDirty(project)) .. '\t'
      .. tostring(reaper.GetProjectStateChangeCount(project))
    index = index + 1
  end
  table.sort(result)
  return result
end

local function write_rows(path, values)
  local file = assert(io.open(path, 'w'))
  file:write('ok=true\n')
  for _, value in ipairs(values) do file:write(value, '\n') end
  file:flush()
  file:close()
end

if c.phase == 'open' then
  local source_project, source_path = reaper.EnumProjects(-1, '')
  assert(source_path == c.source_path, 'source project is not the active tab')
  assert(reaper.GetPlayState() == 0, 'transport must be stopped before adding reopen tab')
  local before = rows()
  local inventory = assert(io.open(c.inventory_path, 'w'))
  inventory:write('ok=true\n')
  for _, value in ipairs(before) do inventory:write(value, '\n') end
  inventory:flush()
  inventory:close()
  local marker = assert(io.open(c.marker_path, 'w'))
  marker:write('stage_start=true\nsource_active=true\nsource_dirty=',
    tostring(reaper.IsProjectDirty(0)), '\nsource_revision=',
    tostring(reaper.GetProjectStateChangeCount(0)), '\n')
  marker:flush()
  local section = reaper.SectionFromUniqueID(0)
  assert(section, 'main action section is unavailable')
  local new_tab_command, new_tab_name
  for index = 0, 10000 do
    local command, name = reaper.kbd_enumerateActions(section, index)
    if command == 0 then break end
    local text = reaper.kbd_getTextFromCmd(command, section) or name or ''
    if text:lower():match('new project tab$') then
      assert(not new_tab_command, 'multiple New project tab actions were found')
      new_tab_command, new_tab_name = command, text
    end
  end
  assert(new_tab_command, 'could not find the native New project tab action')
  reaper.Main_OnCommand(new_tab_command, 0)
  local scratch_project, scratch_path = reaper.EnumProjects(-1, '')
  assert(scratch_project ~= source_project, 'New project tab did not select a separate project')
  assert(scratch_path ~= c.source_path, 'new project tab points to the source project')
  assert(not reaper.IsProjectDirty(scratch_project), 'new scratch tab is unexpectedly dirty')
  marker:write('new_tab_action_id=', tostring(new_tab_command),
    '\nnew_tab_action=', new_tab_name, '\nscratch_path=', scratch_path, '\n')
  marker:flush()
  marker:write('open_call=issued\n')
  marker:flush()
  marker:close()
  reaper.Main_openProject(c.reopened_path)
  return
end

if c.phase == 'verify' then
  assert(active_path() == c.reopened_path, 'byte-identical copy is not active')
  local before_file = assert(io.open(c.inventory_path, 'r'))
  local before = {}
  before_file:read('*l')
  for line in before_file:lines() do before[#before + 1] = line end
  before_file:close()
  local after = rows()
  local expected = {}
  for _, value in ipairs(before) do expected[value] = (expected[value] or 0) + 1 end
  for _, value in ipairs(after) do
    if expected[value] then
      expected[value] = expected[value] - 1
    elseif value:match('^' .. c.reopened_path:gsub('([^%w])', '%%%1') .. '\tfalse\t') then
      assert(not c.reopened_seen, 'reopened tab appears more than once')
      c.reopened_seen = true
    else
      error('unexpected tab or changed source tab state: ' .. value)
    end
  end
  assert(c.reopened_seen, 'new clean reopened tab is absent from inventory')
  for value, count in pairs(expected) do
    assert(count == 0, 'pre-existing tab missing or changed: ' .. value)
  end
  write_rows(c.marker_path, after)
  return
end

error('unknown A01 reopen phase: ' .. tostring(c.phase))
