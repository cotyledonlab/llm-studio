"""Reviewable bootstrap commands; runtime qualification remains explicit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import bootstrap


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
        else:
            result = {"restored": bootstrap.rollback(bootstrap.load_result(args.receipt))}
    except (bootstrap.BootstrapError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
