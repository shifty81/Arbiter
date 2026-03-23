"""Git module implementation using GitPython."""
from __future__ import annotations
from pathlib import Path

try:
    import git as gitlib
    _HAS_GIT = True
except ImportError:
    _HAS_GIT = False


def _repo(path: str):
    if not _HAS_GIT:
        raise RuntimeError("gitpython not installed")
    return gitlib.Repo(path)


def git_init(path: str) -> dict:
    if not _HAS_GIT:
        raise RuntimeError("gitpython not installed")
    r = gitlib.Repo.init(path)
    return {"initialized": str(r.working_dir)}


def git_clone(url: str, path: str) -> dict:
    if not _HAS_GIT:
        raise RuntimeError("gitpython not installed")
    r = gitlib.Repo.clone_from(url, path)
    return {"cloned": url, "to": str(r.working_dir)}


def git_status(path: str) -> dict:
    r = _repo(path)
    return {
        "branch": str(r.active_branch),
        "dirty": r.is_dirty(),
        "untracked": r.untracked_files,
        "staged": [str(d) for d in r.index.diff("HEAD")] if r.head.is_valid() else [],
    }


def git_commit(path: str, message: str) -> dict:
    r = _repo(path)
    r.index.add("*")
    commit = r.index.commit(message)
    return {"committed": str(commit.hexsha), "message": message}


def git_push(path: str, remote: str = "origin", branch: str = "") -> dict:
    r = _repo(path)
    branch = branch or str(r.active_branch)
    r.remote(remote).push(branch)
    return {"pushed": branch, "remote": remote}


def git_pull(path: str, remote: str = "origin", branch: str = "") -> dict:
    r = _repo(path)
    branch = branch or str(r.active_branch)
    r.remote(remote).pull(branch)
    return {"pulled": branch, "remote": remote}


def git_diff(path: str) -> str:
    r = _repo(path)
    return r.git.diff()


def git_log(path: str, count: int = 10) -> list:
    r = _repo(path)
    return [
        {"sha": c.hexsha[:8], "message": c.message.strip(), "author": str(c.author)}
        for c in list(r.iter_commits())[:count]
    ]
