"""Reviewable bootstrap commands; runtime qualification remains explicit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import bootstrap
from .catalogue import Catalogue, CatalogueError


def main() -> int:
    parser = argparse.ArgumentParser(prog="llm-studio")
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("bootstrap-plan", help="Preview and save an immutable setup plan")
    plan.add_argument("--resource", type=Path, required=True)
    plan.add_argument("--controller", type=Path, required=True)
    plan.add_argument("--output", type=Path, required=True)
    apply = commands.add_parser("bootstrap-apply", help="Apply a previously reviewed plan while REAPER is stopped")
    apply.add_argument("plan", type=Path)
    apply.add_argument("--receipt", type=Path, required=True)
    for name in ("bootstrap-verify", "bootstrap-rollback"):
        command = commands.add_parser(name)
        command.add_argument("receipt", type=Path)
    commands.add_parser("catalogue-list", help="List versioned instrument catalogue entries")
    check = commands.add_parser("catalogue-check", help="Verify one instrument's pinned dependencies")
    check.add_argument("instrument_id")
    args = parser.parse_args()
    try:
        if args.command == "bootstrap-plan":
            prepared = bootstrap.plan_bootstrap(args.resource, args.controller)
            bootstrap.save_plan(prepared, args.output)
            result = bootstrap.dry_run(prepared)
        elif args.command == "bootstrap-apply":
            installed = bootstrap.apply(bootstrap.load_plan(args.plan))
            bootstrap.save_result(installed, args.receipt)
            result = {"receipt": str(args.receipt), "backup_dir": str(installed.backup_dir),
                      "changed": installed.changed, "unchanged": installed.unchanged}
        elif args.command == "bootstrap-verify":
            result = bootstrap.verify(bootstrap.load_result(args.receipt))
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        elif args.command == "bootstrap-rollback":
            result = {"restored": bootstrap.rollback(bootstrap.load_result(args.receipt))}
        elif args.command == "catalogue-list":
            catalogue = Catalogue.packaged()
            result = [
                {
                    "id": instrument.id,
                    "name": instrument.data["name"],
                    "role": instrument.data["role"],
                    "qualification": instrument.qualification,
                }
                for instrument in (catalogue.get(identifier) for identifier in catalogue.ids())
            ]
        else:
            instrument = Catalogue.packaged().check_dependencies(args.instrument_id)
            result = {
                "ok": True,
                "id": instrument.id,
                "qualification": instrument.qualification,
                "state_sha256": instrument.data["state_sha256"],
            }
    except (bootstrap.BootstrapError, CatalogueError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
