#!/usr/bin/env python3
"""Capture read-only evidence from the installed REAPER adapter boundary.

This probe never starts REAPER and never writes bridge requests itself.  The
installed ``reaper_connector`` bridge is used only through its public Python
API, while :class:`ReaperStudioAdapter` validates and reads every track.
The operator moves a fader manually between the two observations.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from llm_studio import bootstrap
from llm_studio.reaper import ReaperStudioAdapter


def _source_check(controller: Path) -> dict[str, str]:
    expected = (controller / "src" / "reaper_connector").resolve()
    spec = importlib.util.find_spec("reaper_connector")
    origin = Path(spec.origin).resolve() if spec and spec.origin else None
    if origin is None or not origin.is_relative_to(expected):
        actual = str(origin) if origin else "unavailable"
        raise RuntimeError(
            f"imported reaper_connector source {actual} is outside supplied checkout {expected}"
        )
    return {"expected_source": str(expected), "imported_source": str(origin)}


def _snapshot(adapter: ReaperStudioAdapter) -> dict[str, Any]:
    session = adapter.observe_session()
    tracks = []
    for track in session.tracks:
        state = dict(adapter.read_track(session, track.guid))
        tracks.append({
            "guid": track.guid,
            "name": track.name,
            "index": track.index,
            "state": state,
        })
    return {
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "session": {
            "id": session.id,
            "token": session.token,
            "path": str(session.path),
            "state_change_count": session.state_change_count,
        },
        "tracks": tracks,
        "fx_nonempty": any(bool(item["state"].get("fx")) for item in tracks),
    }


def _changes(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    old = {item["guid"]: item for item in before["tracks"]}
    changed = []
    for item in after["tracks"]:
        prior = old.get(item["guid"])
        if prior is None:
            continue
        a, b = prior["state"], item["state"]
        if a.get("volume") != b.get("volume") or a.get("pan") != b.get("pan"):
            changed.append({
                "guid": item["guid"],
                "before": {"volume": a.get("volume"), "pan": a.get("pan")},
                "after": {"volume": b.get("volume"), "pan": b.get("pan")},
            })
    return changed


def _write_new(path: Path, evidence: dict[str, Any]) -> None:
    if os.path.lexists(path) or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite evidence file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, indent=2, sort_keys=True)
        stream.write("\n")


def _resource_path(value: Path | None) -> Path:
    if value is not None:
        return value.absolute()
    from reaper_connector.doctor import default_resource_path
    return default_resource_path().absolute()


def run(args: argparse.Namespace, *, input_fn: Callable[[str], str] = input) -> dict[str, Any]:
    output = args.output.absolute()
    if os.path.lexists(output) or output.is_symlink():
        raise FileExistsError(f"refusing to overwrite evidence file: {output}")
    if type(args.timeout) not in (int, float) or not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    controller = args.controller.absolute()
    commit = bootstrap.validate_controller_checkout(controller)
    source = _source_check(controller)

    # Import only after proving the selected checkout is the source visible to
    # Python.  No process or bridge request occurs during validation.
    from reaper_connector import bridge

    resource = _resource_path(args.resource)
    def send(operation: str, params: dict[str, Any]) -> dict[str, Any]:
        return bridge.send(operation, params, timeout=args.timeout, resource_path=resource)

    adapter = ReaperStudioAdapter(send)
    before = _snapshot(adapter)
    after = None
    changes: list[dict[str, Any]] = []
    if args.manual_fader:
        try:
            input_fn("Move the target REAPER fader manually, then press Enter to capture the after snapshot: ")
            after = _snapshot(adapter)
            if (before["session"]["id"], before["session"]["token"]) != (after["session"]["id"], after["session"]["token"]):
                raise RuntimeError("manual fader comparison crossed a session change")
            changes = _changes(before, after)
        except Exception as exc:
            partial = {"ok": False, "qualification_pass": False,
                       "error": f"{type(exc).__name__}: {exc}",
                       "controller": {"checkout": str(controller), "commit": commit, **source},
                       "resource": str(resource), "manual_fader": {"before": before, "after": after}}
            _write_new(output, partial)
            return partial
    evidence = {
        "ok": True,
        "qualification_pass": False,
        "qualification_note": "Read observations only; manual fader evidence requires producer review and listening confirmation.",
        "controller": {"checkout": str(controller), "commit": commit, **source},
        "resource": str(resource),
        "snapshot": before,
        "manual_fader": ({"before": before, "after": after, "mixer_changes": changes,
                          "change_observed": bool(changes)} if args.manual_fader else None),
    }
    _write_new(output, evidence)
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller", type=Path, required=True,
                        help="verified pinned reaper-controller checkout")
    parser.add_argument("--resource", type=Path,
                        help="REAPER resource directory used by the bridge")
    parser.add_argument("--output", type=Path, required=True,
                        help="new JSON evidence path (existing files are refused)")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--manual-fader", action="store_true",
                        help="pause for a manual fader move and capture before/after")
    args = parser.parse_args(argv)
    try:
        evidence = run(args)
    except FileExistsError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2
    except Exception as exc:
        try:
            failed_resource = str(_resource_path(args.resource))
        except Exception:
            failed_resource = str(args.resource.absolute()) if args.resource else "unavailable"
        evidence = {"ok": False, "qualification_pass": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "controller": {"checkout": str(args.controller.absolute())},
                    "resource": failed_resource}
        try:
            _write_new(args.output.absolute(), evidence)
        except FileExistsError:
            print(json.dumps({"ok": False, "error": f"refusing to overwrite evidence file: {args.output.absolute()}"}), file=sys.stderr)
            return 2
        print(json.dumps(evidence, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(evidence, indent=2))
    return 0 if evidence.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
