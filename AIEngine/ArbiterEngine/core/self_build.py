"""Arbiter Engine Autonomous Self-Build Loop.

Implements the self-build agent loop:
  roadmap_next → read source → LLM generates code → apply_patch
  → sandbox test → pass: commit+advance / fail: rollback+retry (max 3)

Guardrails:
  - BLOCKED_FILES: files that can never be overwritten
  - max_retries: per-task retry limit (default 3)
  - review_required: tasks tagged with this skip auto-commit
"""
from __future__ import annotations

import asyncio
import datetime
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from core.logger import get_logger

logger = get_logger(__name__)

BLOCKED_FILES: frozenset[str] = frozenset([
    "core/permissions.py",
    "configs/config.toml",
    "configs/permissions.toml",
    ".env",
])

_TELEMETRY_FILE = Path(".arbiter") / "self_build_log.json"
_MAX_SOURCE_CHARS = 12_000
_MAX_FILE_SNIPPET_CHARS = 2_000


def _load_telemetry(base_dir: Path) -> list[dict[str, Any]]:
    path = base_dir / _TELEMETRY_FILE
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_telemetry(base_dir: Path, log: list[dict[str, Any]]) -> None:
    path = base_dir / _TELEMETRY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")


def _roadmap_next(roadmap_file: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    data = json.loads(roadmap_file.read_text(encoding="utf-8"))
    for ms in data.get("milestones", []):
        if ms.get("status") == "done":
            continue
        for task in ms.get("tasks", []):
            if task.get("status") in ("pending", "in_progress"):
                return task, ms
    return None, None


def _mark_task_done(roadmap_file: Path, task_id: str, notes: str = "") -> None:
    data = json.loads(roadmap_file.read_text(encoding="utf-8"))
    for ms in data.get("milestones", []):
        for task in ms.get("tasks", []):
            if task.get("id") == task_id:
                task["status"] = "done"
                if notes:
                    task["notes"] = notes
        tasks = ms.get("tasks", [])
        statuses = {t.get("status") for t in tasks}
        if statuses == {"done"}:
            ms["status"] = "done"
        elif "in_progress" in statuses or ("done" in statuses and "pending" in statuses):
            ms["status"] = "in_progress"
    content = json.dumps(data, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(roadmap_file.parent), suffix=".tmp", prefix=".arbiter_sbld_")
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(content)
        Path(tmp).replace(roadmap_file)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _collect_source_files(base_dir: Path) -> str:
    dirs = [base_dir / "core", base_dir / "llm", base_dir / "modules"]
    parts: list[str] = []
    total = 0
    for d in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*.py")):
            if total >= _MAX_SOURCE_CHARS:
                break
            rel = str(p.relative_to(base_dir))
            if any(rel == blocked for blocked in BLOCKED_FILES):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            snippet = f"### {rel}\n{text[:_MAX_FILE_SNIPPET_CHARS]}\n"
            parts.append(snippet)
            total += len(snippet)
    return "\n".join(parts)


def _apply_patch(base_dir: Path, patch_text: str) -> list[str]:
    if not patch_text.strip():
        return []
    with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False, encoding="utf-8") as tf:
        tf.write(patch_text)
        patch_file = tf.name
    try:
        result = subprocess.run(
            ["patch", "-p1", "--batch", "--input", patch_file],
            cwd=str(base_dir), capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"patch failed:\n{result.stderr}")
        files = re.findall(r"^\+\+\+ b/(.+)$", patch_text, re.MULTILINE)
        return [f.strip() for f in files]
    finally:
        Path(patch_file).unlink(missing_ok=True)


def _run_tests(base_dir: Path, timeout: int = 120) -> tuple[bool, str]:
    import sys
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short", "-q"],
            cwd=str(base_dir), capture_output=True, text=True, timeout=timeout,
        )
        passed = result.returncode == 0
        return passed, (result.stdout + result.stderr)[-4000:]
    except subprocess.TimeoutExpired:
        return False, "Test run timed out"
    except Exception as exc:
        return False, str(exc)


def _git_commit(base_dir: Path, task_title: str, module_hint: str = "") -> bool:
    module_str = module_hint or "core"
    msg = f"feat({module_str}): {task_title}"
    trailer = "\nCo-authored-by: Arbiter <arbiter@bot>"
    full_msg = msg + trailer
    try:
        subprocess.run(["git", "add", "-A"], cwd=str(base_dir), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", full_msg], cwd=str(base_dir), check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning("git commit failed: %s", exc.stderr)
        return False


def _git_rollback(base_dir: Path) -> None:
    try:
        subprocess.run(["git", "checkout", "--", "."], cwd=str(base_dir), check=True, capture_output=True)
        subprocess.run(["git", "clean", "-fd"], cwd=str(base_dir), check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        logger.warning("git rollback error: %s", exc)


class SelfBuildLoop:
    """Drives the autonomous self-build cycle for one roadmap task."""

    MAX_RETRIES = 3

    def __init__(self, base_dir: Path, llm: Any) -> None:
        self.base_dir = base_dir
        self.llm = llm
        self._roadmap_file = base_dir / "workspace" / "roadmap.json"

    async def run(self, emit: Callable[[str], None], task_id: str | None = None) -> dict[str, Any]:
        if not self._roadmap_file.is_file():
            emit("❌ roadmap.json not found\n")
            return {"status": "error", "error": "roadmap.json not found"}

        if task_id:
            data = json.loads(self._roadmap_file.read_text(encoding="utf-8"))
            task = next(
                (t for ms in data.get("milestones", []) for t in ms.get("tasks", []) if t.get("id") == task_id),
                None,
            )
            if task is None:
                emit(f"❌ Task '{task_id}' not found\n")
                return {"status": "error", "error": f"Task '{task_id}' not found"}
        else:
            task, _ms = _roadmap_next(self._roadmap_file)
            if task is None:
                emit("🎉 All roadmap tasks are complete!\n")
                return {"status": "complete"}

        task_id = task["id"]
        task_title = task.get("title", task_id)
        task_desc = task.get("description", "")

        emit(f"🤖 Arbiter self-build: {task_id} — {task_title}\n")

        if task.get("review_required"):
            emit("⚠️  Task requires human review — skipping auto-build\n")
            return {"status": "skipped", "reason": "review_required", "task_id": task_id}

        loop_log: list[str] = []
        attempt = 0
        committed = False

        while attempt < self.MAX_RETRIES:
            attempt += 1
            emit(f"\n── Attempt {attempt}/{self.MAX_RETRIES} ──\n")
            emit("📂 Collecting source context…\n")
            source_ctx = await asyncio.get_event_loop().run_in_executor(None, _collect_source_files, self.base_dir)
            emit("🧠 Asking LLM to generate patch…\n")
            system_msg = (
                "You are a senior software engineer implementing a feature for Arbiter Engine.\n"
                "Produce a valid unified diff (patch -p1 compatible) that implements the task.\n"
                "Rules:\n"
                "  - Output ONLY the diff, no explanation, no markdown fences.\n"
                "  - Do NOT modify: " + ", ".join(sorted(BLOCKED_FILES)) + "\n"
                "  - Keep changes minimal and targeted.\n"
            )
            user_msg = (
                f"Task ID: {task_id}\nTask Title: {task_title}\nTask Description: {task_desc}\n\n"
                f"Current source files (excerpts):\n{source_ctx[:_MAX_SOURCE_CHARS]}"
            )
            try:
                patch_text = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.llm.chat([{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}]),
                )
            except Exception as exc:
                emit(f"❌ LLM error: {exc}\n")
                loop_log.append(f"attempt {attempt}: LLM error: {exc}")
                continue

            patch_text = patch_text.strip()
            if patch_text.startswith("```"):
                lines = patch_text.splitlines()
                inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
                patch_text = "\n".join(inner)

            blocked = [f for f in re.findall(r"^\+\+\+ b/(.+)$", patch_text, re.MULTILINE) if f.strip() in BLOCKED_FILES]
            if blocked:
                emit(f"🚫 Patch touches blocked files: {blocked} — skipping\n")
                loop_log.append(f"attempt {attempt}: blocked files {blocked}")
                break

            emit("🔧 Applying patch…\n")
            try:
                modified = await asyncio.get_event_loop().run_in_executor(None, _apply_patch, self.base_dir, patch_text)
                emit(f"   Modified: {modified}\n")
            except Exception as exc:
                emit(f"❌ Patch failed: {exc}\n")
                loop_log.append(f"attempt {attempt}: patch failed: {exc}")
                await asyncio.get_event_loop().run_in_executor(None, _git_rollback, self.base_dir)
                continue

            emit("🧪 Running tests…\n")
            passed, test_output = await asyncio.get_event_loop().run_in_executor(None, _run_tests, self.base_dir, 120)
            emit(test_output[-2000:] + "\n")

            if passed:
                emit("✅ Tests passed!\n")
                module_hint = task_id.split("-")[0] if "-" in task_id else "core"
                committed = await asyncio.get_event_loop().run_in_executor(None, _git_commit, self.base_dir, task_title, module_hint)
                if committed:
                    emit(f"📦 Committed: feat({module_hint}): {task_title}\n")
                await asyncio.get_event_loop().run_in_executor(None, _mark_task_done, self._roadmap_file, task_id, f"Auto-built attempt {attempt}")
                emit(f"🏁 Task {task_id} marked done!\n")
                loop_log.append(f"attempt {attempt}: SUCCESS")
                break
            else:
                emit(f"❌ Tests failed (attempt {attempt})\n")
                loop_log.append(f"attempt {attempt}: tests failed")
                await asyncio.get_event_loop().run_in_executor(None, _git_rollback, self.base_dir)

        telem = _load_telemetry(self.base_dir)
        entry: dict[str, Any] = {
            "task_id": task_id, "task_title": task_title,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "attempts": attempt, "success": committed, "log": loop_log,
        }
        telem.append(entry)
        await asyncio.get_event_loop().run_in_executor(None, _save_telemetry, self.base_dir, telem)

        return {
            "status": "success" if committed else "failed",
            "task_id": task_id, "task_title": task_title,
            "attempts": attempt, "commit": committed, "log": loop_log,
        }
