"""Local git-backed issues tracker for Arbiter workspaces.

Issues are stored as JSON files under ``<workspace>/.arbiter/issues/<id>.json``
and every mutation is committed to the workspace's git repository so the full
history of the issue log is preserved in the project's VCS.

Layout
------
.arbiter/
  issues/
    0001.json
    0002.json
    ...
    index.json   ← lightweight index (id, title, status, created_at)
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.logger import get_logger

logger = get_logger(__name__)

# ── helpers ──────────────────────────────────────────────────────────────────

def _issues_dir(workspace: str) -> Path:
    return Path(workspace).resolve() / ".arbiter" / "issues"


def _index_path(workspace: str) -> Path:
    return _issues_dir(workspace) / "index.json"


def _issue_path(workspace: str, issue_id: str) -> Path:
    return _issues_dir(workspace) / f"{issue_id}.json"


def _read_index(workspace: str) -> list[dict]:
    p = _index_path(workspace)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _write_index(workspace: str, index: list[dict]) -> None:
    p = _index_path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(index, indent=2), encoding="utf-8")


def _next_id(index: list[dict]) -> str:
    if not index:
        return "0001"
    ids = []
    for e in index:
        try:
            ids.append(int(e["id"]))
        except (KeyError, ValueError):
            continue
    last = max(ids) if ids else 0
    return str(last + 1).zfill(4)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_commit(workspace: str, message: str, paths: list[str]) -> bool:
    """Stage *paths* and commit with *message* in the workspace repo.

    Returns True if the commit succeeded; False otherwise (e.g. git not
    initialised or nothing to commit).
    """
    try:
        subprocess.run(
            ["git", "add", "--"] + paths,
            cwd=workspace,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", message, "--allow-empty"],
            cwd=workspace,
            check=True,
            capture_output=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        logger.warning("git commit failed in %s: %s", workspace, exc)
        return False


# ── public API ────────────────────────────────────────────────────────────────

def issues_create(
    workspace: str,
    title: str,
    body: str = "",
    kind: str = "bug",
    labels: list[str] | None = None,
    **kwargs: Any,
) -> dict:
    """Create a new issue and commit it to the workspace repository.

    *kind* is typically ``"bug"``, ``"crash"``, or ``"task"``.
    *labels* is an optional list of tag strings.
    """
    index = _read_index(workspace)
    issue_id = _next_id(index)
    now = _now_iso()
    issue: dict[str, Any] = {
        "id": issue_id,
        "title": title,
        "body": body,
        "kind": kind,
        "labels": labels or [],
        "status": "open",
        "created_at": now,
        "updated_at": now,
        "comments": [],
    }

    _issues_dir(workspace).mkdir(parents=True, exist_ok=True)
    issue_file = _issue_path(workspace, issue_id)
    issue_file.write_text(json.dumps(issue, indent=2), encoding="utf-8")

    index.append({
        "id": issue_id,
        "title": title,
        "kind": kind,
        "status": "open",
        "created_at": now,
    })
    _write_index(workspace, index)

    _git_commit(
        workspace,
        f"[arbiter-issue] #{issue_id}: {title}",
        [str(issue_file.relative_to(Path(workspace).resolve())), str(_index_path(workspace).relative_to(Path(workspace).resolve()))],
    )
    logger.info("Created issue #%s: %s", issue_id, title)
    return {"status": "created", "issue": issue}


def issues_list(
    workspace: str,
    status: str | None = None,
    kind: str | None = None,
    **kwargs: Any,
) -> dict:
    """Return the issue index, optionally filtered by *status* or *kind*."""
    index = _read_index(workspace)
    if status:
        index = [e for e in index if e.get("status") == status]
    if kind:
        index = [e for e in index if e.get("kind") == kind]
    return {"workspace": workspace, "count": len(index), "issues": index}


def issues_get(workspace: str, issue_id: str, **kwargs: Any) -> dict:
    """Return the full detail record for issue *issue_id*."""
    issue_id = str(issue_id).zfill(4)
    p = _issue_path(workspace, issue_id)
    if not p.exists():
        return {"status": "error", "error": f"Issue #{issue_id} not found"}
    try:
        issue = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"status": "error", "error": str(exc)}
    return {"status": "ok", "issue": issue}


def issues_close(workspace: str, issue_id: str, resolution: str = "", **kwargs: Any) -> dict:
    """Close issue *issue_id*, optionally recording a *resolution* note."""
    issue_id = str(issue_id).zfill(4)
    p = _issue_path(workspace, issue_id)
    if not p.exists():
        return {"status": "error", "error": f"Issue #{issue_id} not found"}
    try:
        issue = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"status": "error", "error": str(exc)}

    now = _now_iso()
    issue["status"] = "closed"
    issue["updated_at"] = now
    issue["closed_at"] = now
    if resolution:
        issue["resolution"] = resolution
    p.write_text(json.dumps(issue, indent=2), encoding="utf-8")

    # Update index entry
    index = _read_index(workspace)
    for entry in index:
        if entry["id"] == issue_id:
            entry["status"] = "closed"
            break
    _write_index(workspace, index)

    _git_commit(
        workspace,
        f"[arbiter-issue] close #{issue_id}: {issue['title']}",
        [str(p.relative_to(Path(workspace).resolve())), str(_index_path(workspace).relative_to(Path(workspace).resolve()))],
    )
    logger.info("Closed issue #%s", issue_id)
    return {"status": "closed", "issue": issue}


def issues_comment(workspace: str, issue_id: str, comment: str, author: str = "arbiter", **kwargs: Any) -> dict:
    """Append a comment to issue *issue_id* and commit the change."""
    issue_id = str(issue_id).zfill(4)
    p = _issue_path(workspace, issue_id)
    if not p.exists():
        return {"status": "error", "error": f"Issue #{issue_id} not found"}
    try:
        issue = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"status": "error", "error": str(exc)}

    now = _now_iso()
    comment_entry = {"author": author, "body": comment, "created_at": now}
    issue.setdefault("comments", []).append(comment_entry)
    issue["updated_at"] = now
    p.write_text(json.dumps(issue, indent=2), encoding="utf-8")

    _git_commit(
        workspace,
        f"[arbiter-issue] comment on #{issue_id}: {issue['title']}",
        [str(p.relative_to(Path(workspace).resolve()))],
    )
    return {"status": "commented", "issue_id": issue_id, "comment": comment_entry}
