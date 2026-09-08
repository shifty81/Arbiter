#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_REMOTE = "https://github.com/shifty81/Cortex.git"
MARKER_REL = Path(".cortex") / "last-green-quality-gate.json"

EXCLUDED_DIR_NAMES = {
    ".git",
    ".cortex",
    ".project_control",
    "artifacts",
    "logs",
    "target",
    "updates",
    "__pycache__",
}

EXCLUDED_TOP_LEVEL = {
    "handoffs",
}

EXCLUDED_SUFFIXES = {
    ".zip",
    ".sha256",
    ".pyc",
    ".pyo",
}


class GitError(RuntimeError):
    pass


def run(cmd: list[str], *, cwd: Path | None = None, check: bool = True, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    cp = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and cp.returncode != 0:
        detail = (cp.stderr or cp.stdout).strip()
        raise GitError(detail or f"Command failed ({cp.returncode}): {' '.join(cmd)}")
    return cp


def git(root: Path, *args: str, check: bool = True, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return run(["git", "-C", str(root), *args], check=check, timeout=timeout)


def git_text(root: Path, *args: str) -> str:
    cp = git(root, *args, check=False)
    return cp.stdout.strip() if cp.returncode == 0 else ""


def git_repo(root: Path) -> bool:
    return git_text(root, "rev-parse", "--is-inside-work-tree").lower() == "true"


def has_commit(root: Path) -> bool:
    return git(root, "rev-parse", "--verify", "HEAD", check=False).returncode == 0


def is_ancestor(root: Path, older: str, newer: str) -> bool:
    return git(root, "merge-base", "--is-ancestor", older, newer, check=False).returncode == 0


def should_skip(root: Path, path: Path) -> bool:
    rel = path.relative_to(root)
    parts = rel.parts
    if not parts:
        return True

    if parts[0] in EXCLUDED_TOP_LEVEL:
        return True

    if any(part in EXCLUDED_DIR_NAMES for part in parts[:-1]):
        return True

    lower_name = path.name.lower()
    if any(lower_name.endswith(suffix) for suffix in EXCLUDED_SUFFIXES):
        return True

    if lower_name.startswith("cortex_debugbundle_"):
        return True

    return False


def snapshot(root: Path) -> dict[str, object]:
    rows: list[str] = []
    path_count = 0

    for path in sorted(root.rglob("*"), key=lambda p: p.as_posix().lower()):
        if not path.is_file() or path.is_symlink():
            continue
        if should_skip(root, path):
            continue

        rel = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        size = path.stat().st_size
        rows.append(f"{rel}\t{size}\t{digest}")
        path_count += 1

    payload = "\n".join(rows).encode("utf-8")
    return {
        "fingerprint": hashlib.sha256(payload).hexdigest(),
        "pathCount": path_count,
    }


def marker_path(root: Path) -> Path:
    return root / MARKER_REL


def load_marker(root: Path) -> dict[str, object]:
    path = marker_path(root)
    if not path.is_file():
        raise GitError(f"No GREEN quality marker exists yet: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise GitError(f"GREEN marker is invalid JSON: {exc}") from exc
    if data.get("schema") != "cortex.green_quality_gate.v1":
        raise GitError(f"Unsupported GREEN marker schema: {data.get('schema')}")
    return data


def certify_matches(root: Path, marker: dict[str, object] | None = None) -> tuple[bool, dict[str, object], str]:
    marker = marker or load_marker(root)
    current = snapshot(root)
    expected = str(marker.get("fingerprint") or "")
    actual = str(current["fingerprint"])
    if not expected:
        return False, current, "GREEN marker contains no source fingerprint."
    if expected != actual:
        return False, current, f"Source changed since Full Quality gate: expected={expected} current={actual}"
    return True, current, "Current governed source matches the last GREEN Full Quality gate."


def current_head(root: Path) -> str:
    return git_text(root, "rev-parse", "HEAD") if git_repo(root) and has_commit(root) else ""


def current_branch(root: Path) -> str:
    return git_text(root, "branch", "--show-current") if git_repo(root) else ""


def mark_green(root: Path) -> int:
    snap = snapshot(root)
    marker = {
        "schema": "cortex.green_quality_gate.v1",
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "project": "Cortex",
        "fingerprint": snap["fingerprint"],
        "pathCount": snap["pathCount"],
        "gitReady": git_repo(root),
        "gitHead": current_head(root) or None,
        "gitBranch": current_branch(root) or None,
    }
    path = marker_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
    print("GREEN SOURCE MARKER: PASS")
    print(f" Fingerprint : {snap['fingerprint']}")
    print(f" Paths       : {snap['pathCount']}")
    print(f" Marker      : {path}")
    return 0


def ensure_origin(root: Path, remote: str) -> None:
    existing = git_text(root, "remote", "get-url", "origin")
    if existing:
        if existing != remote:
            git(root, "remote", "set-url", "origin", remote)
            print(f"Origin updated: {remote}")
    else:
        git(root, "remote", "add", "origin", remote)
        print(f"Origin added: {remote}")


def safe_backup_name(root: Path) -> str:
    base = "cortex-local-history-backup-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    existing = set(git_text(root, "branch", "--format=%(refname:short)").splitlines())
    name = base
    index = 2
    while name in existing:
        name = f"{base}-{index}"
        index += 1
    return name


def setup_or_repair(root: Path, remote: str) -> int:
    if shutil.which("git") is None:
        raise GitError("Git was not found on PATH.")

    before = snapshot(root)
    green_ok = False
    green_reason = "No GREEN marker"
    try:
        green_ok, _, green_reason = certify_matches(root)
    except Exception as exc:
        green_reason = str(exc)

    print("CORTEX GIT WORKING-FOLDER SETUP / REPAIR")
    print(f" Project     : {root}")
    print(f" Remote      : {remote}")
    print(f" Green source: {'MATCH' if green_ok else 'NOT CERTIFIED'}")

    if not git_repo(root):
        cp = run(["git", "init", "-b", "main", str(root)], check=False, timeout=60)
        if cp.returncode != 0:
            run(["git", "init", str(root)], timeout=60)
            git(root, "branch", "-M", "main")
        print("Git repository initialized.")

    branch = current_branch(root)
    if branch and branch != "main":
        git(root, "branch", "-M", "main")
        print(f"Local branch renamed: {branch} -> main")

    ensure_origin(root, remote)
    git(root, "fetch", "origin", "main", timeout=300)

    if git(root, "rev-parse", "--verify", "origin/main", check=False).returncode != 0:
        raise GitError("origin/main could not be resolved after fetch.")

    remote_head = git_text(root, "rev-parse", "origin/main")
    local_head = current_head(root)

    if not local_head:
        relationship = "adopt-remote"
    elif local_head == remote_head:
        relationship = "already-aligned"
    elif is_ancestor(root, local_head, remote_head):
        relationship = "fast-forward-adopt"
    elif is_ancestor(root, remote_head, local_head):
        relationship = "keep-local-ahead"
    else:
        relationship = "divergent-adopt"

    print(f" Local HEAD  : {local_head or '<unborn>'}")
    print(f" origin/main : {remote_head}")
    print(f" Relationship: {relationship}")

    backup = ""
    if relationship in {"adopt-remote", "fast-forward-adopt", "divergent-adopt"}:
        if relationship == "divergent-adopt":
            if not green_ok:
                raise GitError(
                    "Local and remote histories diverge and current source is not certified by the last GREEN marker. "
                    f"Refusing automatic adoption. Detail: {green_reason}"
                )
            backup = safe_backup_name(root)
            git(root, "branch", backup, local_head)
            print(f"Backup branch created: {backup}")

        # Deliberately preserve every working-tree byte while attaching history/index.
        git(root, "reset", "--mixed", "origin/main", timeout=180)
        print("Local main adopted origin/main history without overwriting working files.")

    git(root, "branch", "--set-upstream-to=origin/main", "main", check=False)

    after = snapshot(root)
    if before != after:
        raise GitError(
            "Governed working-source bytes changed during Git setup/repair. "
            "The operation must be inspected before continuing."
        )

    print("WORKING SOURCE PRESERVATION: PASS")
    print(f" Governed paths: {after['pathCount']}")
    print(f" Fingerprint   : {after['fingerprint']}")
    if backup:
        print(f" Recovery ref  : {backup}")

    print("\nGit status after setup/repair:")
    print(git(root, "status", "--short", "--branch", check=False).stdout.strip() or "## main...origin/main")
    return 0


def show_status(root: Path) -> int:
    if not git_repo(root):
        print("Git: Not a repository")
        return 0
    print(git(root, "status", "--short", "--branch", check=False).stdout.rstrip())
    print("\nRemotes:")
    print(git(root, "remote", "-v", check=False).stdout.rstrip() or "<none>")
    try:
        ok, snap, reason = certify_matches(root)
        print(f"\nGREEN source: {'MATCH' if ok else 'MISMATCH'}")
        print(f" {reason}")
        print(f" Fingerprint: {snap['fingerprint']}")
    except Exception as exc:
        print(f"\nGREEN source: unavailable ({exc})")
    return 0


def review(root: Path) -> int:
    if not git_repo(root):
        raise GitError("Cortex is not a Git repository yet.")
    print("STATUS")
    print("------")
    print(git(root, "status", "--short", "--branch", check=False).stdout.rstrip())
    print("\nDIFF STAT")
    print("---------")
    print(git(root, "diff", "--stat", check=False).stdout.rstrip() or "<no unstaged diff>")
    print("\nSTAGED STAT")
    print("-----------")
    print(git(root, "diff", "--cached", "--stat", check=False).stdout.rstrip() or "<no staged diff>")
    return 0


def reset_operational_paths_from_index(root: Path) -> None:
    operational = [
        ".cortex",
        ".project_control",
        "artifacts",
        "logs",
        "target",
        "updates",
        "handoffs",
    ]
    for relative in operational:
        git(root, "reset", "--", relative, check=False)


def stage_governed(root: Path) -> None:
    git(root, "add", "-A")
    reset_operational_paths_from_index(root)


def commit_green(root: Path, message: str) -> int:
    if not git_repo(root):
        raise GitError("Cortex is not a Git repository yet.")

    ok, _, reason = certify_matches(root)
    if not ok:
        raise GitError(reason)

    stage_governed(root)

    staged = git(root, "diff", "--cached", "--quiet", check=False)
    if staged.returncode == 0:
        print("Nothing governed is staged; no commit needed.")
        return 0

    git(root, "commit", "-m", message, timeout=180)
    print("GREEN commit created.")
    print(git(root, "log", "-1", "--oneline", check=False).stdout.strip())
    return 0


def push_main(root: Path) -> int:
    if not git_repo(root):
        raise GitError("Cortex is not a Git repository yet.")
    git(root, "push", "-u", "origin", "main", timeout=300)
    print("Push to origin/main: PASS")
    return 0


def commit_push_green(root: Path, message: str) -> int:
    commit_green(root, message)
    return push_main(root)


def pull_ff_only(root: Path) -> int:
    if not git_repo(root):
        raise GitError("Cortex is not a Git repository yet.")
    git(root, "pull", "--ff-only", "origin", "main", timeout=300)
    print("Fast-forward-only pull: PASS")
    return 0


def manual_commit(root: Path, message: str) -> int:
    if not git_repo(root):
        raise GitError("Cortex is not a Git repository yet.")
    git(root, "add", "-A")
    staged = git(root, "diff", "--cached", "--quiet", check=False)
    if staged.returncode == 0:
        print("Nothing staged; no commit needed.")
        return 0
    git(root, "commit", "-m", message, timeout=180)
    print("Manual commit created. This path is not GREEN-gate certified.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Cortex canonical local Git/source-control authority.")
    parser.add_argument("action", choices=[
        "status",
        "setup",
        "repair",
        "review",
        "mark-green",
        "commit-green",
        "commit-push-green",
        "push",
        "pull",
        "manual-commit",
    ])
    parser.add_argument("--root", required=True)
    parser.add_argument("--remote", default=DEFAULT_REMOTE)
    parser.add_argument("--message", default="")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        raise GitError(f"Project root does not exist: {root}")

    if args.action == "mark-green":
        return mark_green(root)
    if args.action in {"setup", "repair"}:
        return setup_or_repair(root, args.remote)
    if args.action == "status":
        return show_status(root)
    if args.action == "review":
        return review(root)
    if args.action == "commit-green":
        return commit_green(root, args.message or "Cortex GREEN checkpoint")
    if args.action == "commit-push-green":
        return commit_push_green(root, args.message or "Cortex GREEN checkpoint")
    if args.action == "push":
        return push_main(root)
    if args.action == "pull":
        return pull_ff_only(root)
    if args.action == "manual-commit":
        return manual_commit(root, args.message or "Cortex manual checkpoint")

    raise GitError(f"Unsupported action: {args.action}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GitError as exc:
        print(f"FAIL: {exc}")
        raise SystemExit(1)
    except subprocess.TimeoutExpired as exc:
        print(f"FAIL: command timed out: {exc}")
        raise SystemExit(1)
