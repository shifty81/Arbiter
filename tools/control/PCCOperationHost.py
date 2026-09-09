#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from PCCRepoHygiene import prepare

VERSION = "PCC-OPERATION-HOST-0.1"

# Operations that should begin and end from a transport-clean repository root.
CLEAN_OPERATIONS = {
    "full", "quick", "fast", "build", "build-release", "self-test",
    "commit-green", "commit-push-green", "push", "git-pull",
    "debug-bundle", "doctor", "root-hygiene", "root-hygiene-fix",
}


def _print_hygiene(label: str, root: Path) -> int:
    try:
        result = prepare(root, apply=True)
    except Exception as exc:
        print(f"[FAIL] {label} repository transport hygiene failed: {exc}", flush=True)
        return 1
    moved = int(result.get("moved", 0) or 0)
    if moved:
        print(f"[PASS] {label} repository transport hygiene moved {moved} operational artifact(s).", flush=True)
        for row in result.get("moves", []):
            print(f"  MOVE {Path(row['source']).name} -> {row['destination']}", flush=True)
    else:
        print(f"[PASS] {label} repository transport hygiene clean.", flush=True)
    pending = result.get("pendingPatchTransports") or []
    if pending:
        print(f"[INFO] {len(pending)} pending patch transport(s) preserved for project update authority.", flush=True)
    return 0


def _run(argv: Sequence[str], root: Path) -> int:
    env = os.environ.copy()
    env["PCC_OPERATION_HOST_ACTIVE"] = "1"
    proc = subprocess.Popen(list(argv), cwd=str(root), stdin=subprocess.DEVNULL, env=env)
    return int(proc.wait())


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Universal PCC operation host")
    ap.add_argument("--root", required=True)
    ap.add_argument("--operation", required=True)
    ap.add_argument("child", nargs=argparse.REMAINDER)
    ns = ap.parse_args(argv)
    root = Path(ns.root).expanduser().resolve()
    operation = str(ns.operation)
    child = list(ns.child)
    if child and child[0] == "--":
        child = child[1:]
    if not child:
        print("[FAIL] PCC operation host received no provider command.", flush=True)
        return 2

    do_clean = operation in CLEAN_OPERATIONS
    if do_clean and _print_hygiene("Pre-operation", root) != 0:
        return 1

    print(f"[PCC] Operation host {VERSION}: {operation}", flush=True)
    rc = 1
    try:
        rc = _run(child, root)
    finally:
        if do_clean:
            clean_rc = _print_hygiene("Post-operation", root)
            if rc == 0 and clean_rc != 0:
                rc = clean_rc
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
