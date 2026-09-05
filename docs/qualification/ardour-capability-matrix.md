# Ardour capability matrix

Status vocabulary:

- **Observed**: exercised against an installed, running target build.
- **Source-only**: present in the inspected upstream source schema/code, but not runtime-qualified.
- **Unknown**: neither demonstrated nor disproved on the target build.
- **Failed**: an acceptance requirement was exercised and did not pass.

No Ardour build is installed on the target Mac, so no entry is marked Observed. Source-only entries are not passing runtime evidence.

| Required capability | Target result | Upstream source observation at `ba38f08e` | Gate consequence |
|---|---|---|---|
| No-purchase runnable build | **Failed** | Source is obtainable without purchase; configure stops at missing Boost and upstream requires a separately maintained dependency stack | Blocks all runtime checks |
| Actual MCP discovery/schema | **Unknown** | `tools_json.inc` declares tool schemas; server reports version `0.1.0` in source | Installed schema was not available and is not inferred |
| Endpoint binding | **Unknown** | Endpoint display uses `127.0.0.1`, while server construction shown in source does not set a libwebsockets interface; the current manual warns that all-interface listening is the default | Must verify with `lsof`/socket tests on the built process; correct exposure before use |
| Stable track IDs | **Unknown** | `tracks_list` and track tools include ID-shaped fields | Rename/reorder/delete persistence not exercised |
| Audio import | **Unknown** | No audio-file import tool appears in the inspected tool-name list | Essential Gate A step lacks runtime evidence and appears absent from native MCP |
| Read gain | **Unknown** | `track_get_fader` and `track_get_info` appear in source | Manual edit/readback not exercised |
| Set gain | **Unknown** | `track_set_fader_position` and `track_set_fader_db` appear in source | Not exercised |
| Read pan | **Unknown** | `track_get_info` description says it returns pan | Manual edit/readback not exercised |
| Set pan | **Unknown** | `track_set_pan` appears in source | Not exercised |
| Read automation envelope | **Unknown / apparent native gap** | No automation/envelope read tool appears in the inspected schema | Essential capability; blocks automatic mix application unless a narrow native adapter proves it |
| Write bounded automation envelope | **Unknown / apparent native gap** | No automation/envelope write tool appears in the inspected schema | Essential capability; blocks automatic mix application unless a narrow native adapter proves it |
| External edit notifications | **Unknown / apparent native gap** | No subscription or notification tool appears in the inspected schema | Conflict detection remains unsafe |
| Undo/redo | **Unknown** | `session_undo` and `session_redo` appear in source | Not exercised with bounded proposal |
| Save/reopen | **Unknown** | `session_save` appears; reopen is not represented in the tool list | Not exercised |
| Part replacement preserving mix | **Unknown** | Region move/copy/resize tools appear, but no audio import tool was found | Not exercised |
| Stereo export | **Unknown / apparent native gap** | No session audio export tool appears in the inspected schema; MIDI JSON export is unrelated | Required final export not demonstrated |
| Atomic conflict check-and-apply | **Unknown / apparent native gap** | No revision token, compare-and-swap or atomic envelope proposal operation appears in schema | Unsafe conflict model blocks automatic mix application |

## Source schema inventory

The inspected upstream schema covers session save/undo/redo, transport, markers, tracks and buses, fader/pan/mute/solo, sends, plugins, region edits, and MIDI region/note editing. It does not establish behavior of any installed build. In particular, a fader setter is not evidence of automation-envelope editing.

Actual installed schemas must be captured by running [`scripts/probe-ardour-mcp.sh`](../../scripts/probe-ardour-mcp.sh) after a qualified build is running and MCPHttp has been enabled by the producer. The script refuses non-loopback URLs and performs only MCP initialization and `tools/list`.
