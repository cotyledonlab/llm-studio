# LLM Studio

A producer-led studio with agent session musicians and an engineer. Agents communicate through native software interfaces; the producer retains the DAW's mixer, processing controls and editable automation.

**Status:** REAPER is the selected DAW direction. SuperCollider NRT and Pedalboard/Dexed rendering have been qualified; the integrated REAPER Gate A remains to be completed.

## Start here

- [Product and engineering specification](SPEC.md) — requirements, architecture, contracts, manual-control rules and acceptance matrix.
- [Implementation plan](docs/IMPLEMENTATION_PLAN.md) — epics, dependency map and exact next tasks.
- [Issues](https://github.com/cotyledonlab/llm-studio/issues) — 7 epics and 24 detailed implementation issues.
- **First task:** [adopt and automate the existing REAPER controller](https://github.com/cotyledonlab/llm-studio/issues/9).

## The experience

Describe an eight-bar arrangement. Hear alternative drum, bass and keys performances. Choose takes. Mix and draw automation yourself in REAPER. Ask an agent to revise the drums without losing your bass level or keys automation. Save, reopen and export.

## Architecture direction

- **REAPER:** selected mixer/timeline. Reuse the proven `reaper-controller` bridge, OSC, MIDI and project-file lanes; automate its safe one-time setup instead of building another connector.
- **SuperCollider:** reuse the existing synthesis connector for background rendering.
- **Python renderer:** Pedalboard with Dexed is the selected initial plugin worker; evaluate DawDreamer only after a concrete Pedalboard failure.
- **Local coordinator:** one writer for approved session changes; bounded parallel musician generation and isolated render jobs.
- **Instrument catalogue:** a small qualified kit/bass/keys baseline, with programmatic state recall and clear asset provenance.

No agent-driven GUI automation. A paid REAPER licence is an accepted studio prerequisite; model inference, plugins, sample content and other optional sounds remain separately visible costs. Plugin installation is catalogue provisioning: agents may install only producer-approved, pinned packages with licence/provenance checks and post-install qualification, never arbitrary binaries during a take.

## Delivery gates

1. **Gate A:** prove manual mixer/automation control, programmatic readback, conflict handling, replacement, reopen and export.
2. **Gate B:** prove sound rendering, state recall, alignment and cancellation.
3. **Gate C:** hear a useful producer-led musical workflow before expanding infrastructure.

The Ardour investigation is retained as a historical no-go. Existing `reaper-controller` evidence accelerates Gate A but does not automatically prove the studio-specific automation, conflict and take-replacement contracts.

## Scope

The first release supports a small ensemble and gain/pan/volume-automation engineering. Universal genres, every plugin, remote access, live agent jamming and autonomous mastering are later possibilities, not v1 promises.

## Licensing

No licence for this repository's future implementation has been selected yet. Before distributing implementation code, choose a licence consistent with the selected dependencies. Do not commit plugins, private recordings or sample libraries without appropriate redistribution rights.
