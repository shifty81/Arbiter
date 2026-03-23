"""Filesystem module implementation."""
from __future__ import annotations
import shutil
from pathlib import Path


def read_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def write_file(path: str, content: str) -> dict:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"written": str(p), "bytes": len(content.encode())}


def list_directory(path: str) -> list:
    return [str(p) for p in sorted(Path(path).iterdir())]


def delete_file(path: str) -> dict:
    p = Path(path)
    if p.is_dir():
        shutil.rmtree(p)
    else:
        p.unlink()
    return {"deleted": str(p)}


def copy_file(src: str, dst: str) -> dict:
    s, d = Path(src), Path(dst)
    d.parent.mkdir(parents=True, exist_ok=True)
    if s.is_dir():
        shutil.copytree(s, d)
    else:
        shutil.copy2(s, d)
    return {"copied": str(s), "to": str(d)}


def move_file(src: str, dst: str) -> dict:
    s, d = Path(src), Path(dst)
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s), str(d))
    return {"moved": str(s), "to": str(d)}
