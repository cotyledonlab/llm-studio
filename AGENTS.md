# llm-studio agent orientation

Read HANDOFF.md and verify the current branch, issue/PR state, and outstanding acceptance before continuing implementation. Use the current spec and qualification reports for the slice being changed.

For REAPER operations, use the shared operating skill at `.agents/skills/reaper/SKILL.md`, which links to the adjacent `../reaper-controller/skills/reaper` directory. If the sibling checkout is absent, locate the existing reaper-controller checkout and read its `skills/reaper/SKILL.md` and `AGENTS.md` before live work; do not substitute GUI automation.

Follow that controller's native bridge/OSC/MIDI/file protocols. Keep live DAW mutations under one owner, preserve producer edits, and independently read back changes. Use disposable projects for qualification. Passing code tests does not replace the slice's real-REAPER acceptance or requested listening checks.
