"""Qualify volume-envelope attachment semantics against a disposable copy."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time

CASES = (
    ("project_time_inherited", 0, -1, 0, 2, 2),
    ("project_beats_all_inherited", 1, -1, 1, 4, 4),
    ("project_beats_position_inherited", 2, -1, 2, 4, 4),
    ("track_beats_overrides_time", 0, 1, 1, 4, 4),
    ("track_beats_position_overrides_time", 0, 2, 2, 4, 4),
    ("track_time_overrides_beats", 1, 0, 0, 2, 2),
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--cfgfile", required=True, type=Path)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    cfgfile = args.cfgfile.resolve(strict=True)
    base = Path("/private/tmp/llm-studio-reaper")
    if not source.is_relative_to(base) or source.suffix.lower() != ".rpp":
        parser.error("source must be a disposable RPP under /private/tmp/llm-studio-reaper")
    if not cfgfile.is_relative_to(base) or cfgfile.name != "reaper.ini":
        parser.error("cfgfile must be a disposable reaper.ini under /private/tmp/llm-studio-reaper")
    root = Path(tempfile.mkdtemp(prefix="automation-timebase-", dir=base))
    repo = Path(__file__).resolve().parents[2]
    wrappers = []
    for name, project, track, effective, after_sec, after_qn in CASES:
        config = {"root": str(root), "source": str(source), "profile": str(cfgfile.parent),
                  "handler": str(repo / "adapters/reaper/studio_handler.lua"), "name": name,
                  "project": project, "track": track, "effective": effective,
                  "after_sec": after_sec, "after_qn": after_qn}
        wrapper = root / f"{name}.lua"
        wrapper.write_text("STUDIO_AUTOMATION_TIMEBASE = {\n" + "".join(
            f"  {key} = {json.dumps(value)},\n" for key, value in config.items()) + "}\n"
            + f"dofile({json.dumps(str(Path(__file__).with_suffix('.lua')))})\n", encoding="utf-8")
        wrappers.append((name, wrapper))
    print(root, flush=True)
    if not args.run:
        return
    source_bytes = source.read_bytes()
    evidence_parts = []
    for name, wrapper in wrappers:
        subprocess.run(["/Applications/REAPER.app/Contents/MacOS/REAPER", "-cfgfile", str(cfgfile),
                        "-nonewinst", "-noactivate", str(wrapper)], check=True, timeout=20)
        case_report = root / f"{name}.txt"
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            evidence = case_report.read_text(encoding="utf-8") if case_report.exists() else ""
            if "case_qualification=" in evidence:
                if "case_qualification=pass" not in evidence or "source_tab_restored=true" not in evidence:
                    raise RuntimeError(f"timebase qualification failed; inspect {case_report}")
                evidence_parts.append(evidence)
                break
            time.sleep(0.05)
        else:
            raise TimeoutError(f"timebase completion unobserved; inspect {case_report}")
    if source.read_bytes() != source_bytes:
        raise RuntimeError("source project file changed during timebase qualification")
    report = root / "timebase-evidence.txt"
    report.write_text("".join(evidence_parts) + "timebase_qualification=pass\n", encoding="utf-8")
    print(f"Timebase qualification passed: {report}")


if __name__ == "__main__":
    main()
