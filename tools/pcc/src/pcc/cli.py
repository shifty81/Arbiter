from __future__ import annotations

import argparse
import json
from pathlib import Path

from .archive_audit import audit_archive
from .control import command_catalog, discover, load_project, run_command, run_gate, status


def _emit(value: object, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(value, indent=2, sort_keys=True))
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                print(f"{key}: {json.dumps(item, sort_keys=True)}")
            else:
                print(f"{key}: {item}")
    elif isinstance(value, list):
        for item in value:
            print(json.dumps(item, sort_keys=True))
    else:
        print(value)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pcc", description="Universal Project Control Center")
    p.add_argument("--project-root", default=".")
    p.add_argument("--json", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("status")
    sub.add_parser("catalog")
    archive_audit = sub.add_parser("archive-audit")
    archive_audit.add_argument("archive")
    archive_audit.add_argument("--prefix", default="")
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--strict", action="store_true")

    run = sub.add_parser("run")
    run.add_argument("key")
    run.add_argument("--allow-mutation", action="store_true")

    gate = sub.add_parser("gate")
    gate.add_argument("key")

    scan = sub.add_parser("discover")
    scan.add_argument("roots", nargs="+")
    scan.add_argument("--max-depth", type=int, default=5)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "discover":
            if args.max_depth < 0 or args.max_depth > 32:
                raise ValueError("--max-depth must be between 0 and 32")
            value = {"schema": "pcc.discovery.v1", "projects": discover(args.roots, args.max_depth)}
            _emit(value, args.json)
            return 0

        control = load_project(Path(args.project_root))
        if args.command == "status":
            value = status(control)
        elif args.command == "archive-audit":
            value = audit_archive(control.root, args.archive, args.prefix)
        elif args.command == "catalog":
            value = {"schema": "pcc.catalog.v1", "commands": command_catalog(control)}
        elif args.command == "doctor":
            value = status(control)
            if args.strict and not value["ready"]:
                _emit(value, args.json)
                return 2
        elif args.command == "run":
            value = run_command(control, args.key, allow_mutation=args.allow_mutation, stream=not args.json)
        elif args.command == "gate":
            value = run_gate(control, args.key, stream=not args.json)
        else:
            raise RuntimeError(f"unsupported command: {args.command}")
        _emit(value, args.json)
        if isinstance(value, dict) and value.get("success") is False:
            return 1
        return 0
    except Exception as exc:
        payload = {"schema": "pcc.error.v1", "error": str(exc), "type": type(exc).__name__}
        _emit(payload, args.json)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
