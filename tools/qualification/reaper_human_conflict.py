"""Arm the native human-edit conflict qualification against a disposable session.

The generated ReaScript observes the active volume envelope and waits for the
producer to move its existing two-second point.  It refreshes an unchanged
observation every 20 seconds, so the eventual edit can be tested within the
handler's 30-second freshness bound.  The stale proposal must be rejected and
the producer's exact edited envelope is then saved.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--cfgfile", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    source = args.source.resolve(strict=True)
    cfgfile = args.cfgfile.resolve(strict=True)
    output = args.output.absolute()
    base = Path("/private/tmp/llm-studio-reaper")
    if not source.is_relative_to(base) or source.suffix.lower() != ".rpp":
        parser.error("source must be a disposable RPP under /private/tmp/llm-studio-reaper")
    if not cfgfile.is_relative_to(base) or cfgfile.name != "reaper.ini":
        parser.error("cfgfile must be a disposable reaper.ini under /private/tmp/llm-studio-reaper")
    if output.exists() or output.is_symlink():
        parser.error("output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)

    repo = Path(__file__).resolve().parents[2]
    lua = Path(__file__).with_suffix(".lua")
    config = {
        "source": str(source),
        "profile": str(cfgfile.parent),
        "output": str(output),
        "handler": str(repo / "adapters/reaper/studio_handler.lua"),
    }
    wrapper = output.with_suffix(".lua")
    if wrapper.exists() or wrapper.is_symlink():
        parser.error("wrapper already exists")
    wrapper.write_text(
        "STUDIO_HUMAN_CONFLICT = {\n"
        + "".join(f"  {key} = {json.dumps(value)},\n" for key, value in config.items())
        + "}\n"
        + f"dofile({json.dumps(str(lua))})\n",
        encoding="utf-8",
    )
    print(wrapper)


if __name__ == "__main__":
    main()
