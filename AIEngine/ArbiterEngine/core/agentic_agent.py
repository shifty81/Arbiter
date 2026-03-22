"""Arbiter Engine Agentic Chat Engine — plans tasks, executes file edits, tracks changes.

Flow:
  user message
    └─ LLM plans → TodoItem list
         └─ for each task: LLM proposes file edits → apply → diff
  return AgenticResult(reply, todos, file_changes)
"""
from __future__ import annotations

import difflib
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from core.logger import get_logger
from llm.base import BaseLLM

logger = get_logger(__name__)


@dataclass
class TodoItem:
    id: str
    text: str
    done: bool = False


@dataclass
class FileChange:
    path: str
    additions: int
    deletions: int
    diff: str
    original_content: str
    new_content: str


@dataclass
class AgenticResult:
    reply: str
    todos: list[TodoItem] = field(default_factory=list)
    file_changes: list[FileChange] = field(default_factory=list)


class AgenticChatEngine:
    """Drives the agentic loop: plan → execute file edits → summarize."""

    def __init__(self, llm: BaseLLM, base_dir: Path, project_path: str = "") -> None:
        self.llm = llm
        self.base_dir = base_dir.resolve()
        self.project_path = project_path

    def run(self, message: str, on_event: Callable[[dict[str, Any]], None] | None = None) -> AgenticResult:
        emit = on_event or (lambda _e: None)
        emit({"type": "thinking", "text": "Planning tasks…"})
        todos = self._plan(message)
        emit({"type": "todos", "todos": [{"id": t.id, "text": t.text, "done": t.done} for t in todos]})
        file_changes: list[FileChange] = []
        for todo in todos:
            emit({"type": "todo_active", "id": todo.id, "text": todo.text})
            edits = self._propose_edits(message, todo.text)
            for edit in edits:
                path = edit.get("path", "")
                new_content = edit.get("content", "")
                if not path or new_content is None:
                    continue
                emit({"type": "generating_patch", "path": path})
                change = self._apply_edit(path, new_content)
                if change:
                    file_changes.append(change)
                    emit({"type": "file_edited", "path": change.path, "additions": change.additions, "deletions": change.deletions})
            todo.done = True
            emit({"type": "todo_done", "id": todo.id})
        emit({"type": "thinking", "text": "Writing summary…"})
        reply = self._summarize(message, todos, file_changes)
        emit({"type": "done"})
        return AgenticResult(reply=reply, todos=todos, file_changes=file_changes)

    def _plan(self, message: str) -> list[TodoItem]:
        system = (
            "You are a planning assistant. "
            "Given a user request, break it into a concise numbered task list. "
            "Return ONLY the numbered list, one task per line. "
            "Keep each task under 80 characters. Maximum 8 tasks."
        )
        messages = [{"role": "system", "content": system}, {"role": "user", "content": message}]
        raw = self.llm.generate(messages)
        return _parse_todo_list(raw)

    def _propose_edits(self, original_message: str, task: str) -> list[dict[str, Any]]:
        ws_tree = _list_workspace(self.base_dir, self.project_path, max_depth=2)
        system = (
            "You are an expert software engineer working inside Arbiter IDE.\n"
            "Given a task and the current workspace file tree, identify which files need "
            "to be created or modified and provide the complete new file content.\n\n"
            "Respond ONLY with a JSON array of objects, each with:\n"
            '  "path": relative workspace path\n'
            '  "content": full new file content (string)\n\n'
            "Return [] if no files need to be changed."
        )
        user_msg = f"Original user request: {original_message}\n\nCurrent task: {task}\n\nWorkspace tree:\n{ws_tree}"
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user_msg}]
        raw = self.llm.generate(messages)
        return _parse_edit_list(raw)

    def _apply_edit(self, rel_path: str, new_content: str) -> FileChange | None:
        try:
            target = _safe_path(self.base_dir, rel_path)
        except ValueError as exc:
            logger.warning("Agentic edit blocked (path traversal): %s", exc)
            return None
        try:
            original = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
        except Exception as exc:
            logger.warning("Could not read %s: %s", target, exc)
            original = ""
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(new_content, encoding="utf-8")
        except Exception as exc:
            logger.error("Could not write %s: %s", target, exc)
            return None
        diff_lines = list(difflib.unified_diff(
            original.splitlines(keepends=True), new_content.splitlines(keepends=True),
            fromfile=f"a/{rel_path}", tofile=f"b/{rel_path}", lineterm="",
        ))
        diff_text = "".join(diff_lines)
        additions = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
        deletions = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))
        return FileChange(path=rel_path, additions=additions, deletions=deletions,
                          diff=diff_text, original_content=original, new_content=new_content)

    def _summarize(self, original_message: str, todos: list[TodoItem], file_changes: list[FileChange]) -> str:
        done_count = sum(1 for t in todos if t.done)
        changed_files = [c.path for c in file_changes]
        files_summary = f"Changed files: {', '.join(changed_files)}" if changed_files else "No files were changed."
        system = "You are a helpful assistant summarizing completed work. Write a concise, friendly summary (2-4 sentences). Use markdown. Mention the files that were changed."
        user_msg = f"Original request: {original_message}\n\nTasks completed: {done_count}/{len(todos)}\n{files_summary}"
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user_msg}]
        return self.llm.generate(messages)


def _parse_todo_list(text: str) -> list[TodoItem]:
    todos: list[TodoItem] = []
    for line in text.strip().splitlines():
        stripped = re.sub(r"^\s*\d+[.)]\s*", "", line).strip()
        if stripped:
            todos.append(TodoItem(id=str(uuid.uuid4())[:8], text=stripped))
    return todos or [TodoItem(id=str(uuid.uuid4())[:8], text="Complete the request")]


def _parse_edit_list(text: str) -> list[dict[str, Any]]:
    text = re.sub(r"```(?:json)?\n?", "", text).replace("```", "").strip()
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return []
    try:
        edits = json.loads(m.group(0))
        if isinstance(edits, list):
            return [e for e in edits if isinstance(e, dict) and "path" in e and "content" in e]
    except (json.JSONDecodeError, ValueError):
        pass
    return []


def _safe_path(base_dir: Path, rel_path: str) -> Path:
    _ALLOWED_ROOTS = {"workspace", "projects"}
    parts = Path(rel_path).parts
    root = parts[0] if parts else ""
    if root not in _ALLOWED_ROOTS:
        raise ValueError(f"Path root '{root}' not in allowed roots {_ALLOWED_ROOTS}")
    target = (base_dir / rel_path).resolve()
    if not str(target).startswith(str(base_dir)):
        raise ValueError(f"Path traversal attempt: {rel_path!r}")
    return target


def _list_workspace(base_dir: Path, project_path: str, max_depth: int = 2) -> str:
    roots = []
    for root_name in ("workspace", "projects"):
        root = base_dir / root_name
        if root.is_dir():
            roots.append(root)
    if project_path:
        proj = (base_dir / project_path).resolve()
        if proj.is_dir() and str(proj).startswith(str(base_dir)):
            roots.append(proj)
    lines: list[str] = []
    for root in roots:
        _walk(root, base_dir, max_depth, 0, lines)
    return "\n".join(lines[:80]) if lines else "(empty workspace)"


def _walk(path: Path, base_dir: Path, max_depth: int, depth: int, out: list[str]) -> None:
    indent = "  " * depth
    rel = str(path.relative_to(base_dir))
    out.append(f"{indent}{rel}/") if path.is_dir() else out.append(f"{indent}{rel}")
    if depth < max_depth and path.is_dir():
        try:
            for child in sorted(path.iterdir())[:20]:
                _walk(child, base_dir, max_depth, depth + 1, out)
        except PermissionError:
            pass
