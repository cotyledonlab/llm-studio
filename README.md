# LLM Studio

A producer-led studio with agent session musicians and an engineer. Agents communicate through native software interfaces; the producer retains the DAW's mixer, processing controls and editable automation.

**Status:** specification and implementation backlog only. No studio runtime or backend qualification has been completed in this repository.

## Start here

- [Product and engineering specification](SPEC.md) — requirements, architecture, contracts, manual-control rules and acceptance matrix.
- [Implementation plan](docs/IMPLEMENTATION_PLAN.md) — epics, dependency map and exact next tasks.
- [Issues](https://github.com/cotyledonlab/llm-studio/issues) — 7 epics and 23 detailed implementation issues.
- **First task:** [qualify the no-purchase Ardour build and discover its real APIs](https://github.com/cotyledonlab/llm-studio/issues/8).

## The experience

Describe an eight-bar arrangement. Hear alternative drum, bass and keys performances. Choose takes. Mix and draw automation yourself in Ardour. Ask an agent to revise the drums without losing your bass level or keys automation. Save, reopen and export.

## Architecture direction

- **Ardour:** candidate native mixer/timeline, conditional on real macOS qualification. Investigate its experimental native MCP surface before creating another connector.
- **SuperCollider:** reuse the existing synthesis connector for background rendering.
- **Python renderer:** qualify Pedalboard first; evaluate DawDreamer only if needed. Select one production plugin worker.
- **Local coordinator:** one writer for approved session changes; bounded parallel musician generation and isolated render jobs.
- **Instrument catalogue:** a small qualified kit/bass/keys baseline, with programmatic state recall and clear asset provenance.

No agent-driven GUI automation and no mandatory paid DAW licence. Ardour's free source-build route must be made practical on the target Mac; paid official builds are optional conveniences, not the baseline. Model inference and optional sounds are separate costs.

## Delivery gates

1. **Gate A:** prove manual mixer/automation control, programmatic readback, conflict handling, replacement, reopen and export.
2. **Gate B:** prove sound rendering, state recall, alignment and cancellation.
3. **Gate C:** hear a useful producer-led musical workflow before expanding infrastructure.

All initial issues are open. Documentation of a native API does not prove that the installed build supports every required capability.

## Scope

The first release supports a small ensemble and gain/pan/volume-automation engineering. Universal genres, every plugin, remote access, live agent jamming and autonomous mastering are later possibilities, not v1 promises.

## Licensing

No licence for this repository's future implementation has been selected yet. Before distributing implementation code, choose a licence consistent with the selected dependencies. Do not commit plugins, private recordings or sample libraries without appropriate redistribution rights.
