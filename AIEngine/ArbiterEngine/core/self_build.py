"""Arbiter Engine Autonomous Self-Build Loop.

Implements the full M7 self-build agent pipeline:

  M7-1:  SelfBuildController — orchestrator wrapping SelfBuildLoop
  M7-2:  Four autonomy modes: Manual, Assist, SemiAuto, FullAuto
  M7-3:  Task planning — AI generates step-by-step implementation plan
  M7-4:  File identification — AI identifies files to create/modify
  M7-5:  Code generation — AI writes unified diff for each change
  M7-6:  Syntax validation — Python AST check before applying patch
  M7-7:  Test execution — pytest / dotnet test / npm test
  M7-8:  Iteration loop — retry up to 3 times before requesting review
  M7-9:  Structured commit message: [arbiter-self-build] <task_id>: <title>
  M7-10: Roadmap update — mark task done with implementation notes

Guardrails:
  - BLOCKED_FILES: files that can never be overwritten
  - max_retries: per-task retry limit (default 3)
  - review_required: tasks tagged with this skip auto-commit
"""
from __future__ import annotations

import ast
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


def _mark_task_in_progress(roadmap_file: Path, task_id: str) -> None:
    """Set a single task to in_progress so the panel shows current work."""
    data = json.loads(roadmap_file.read_text(encoding="utf-8"))
    for ms in data.get("milestones", []):
        for task in ms.get("tasks", []):
            if task.get("id") == task_id:
                task["status"] = "in_progress"
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


# ── M7-6: Syntax validation ───────────────────────────────────────────────────

def _validate_python_syntax(path: Path) -> list[str]:
    """Return a list of syntax error messages for the given Python file.

    Returns an empty list when the file is syntactically valid.
    """
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        ast.parse(source, filename=str(path))
        return []
    except SyntaxError as exc:
        return [f"{path}: SyntaxError at line {exc.lineno}: {exc.msg}"]
    except Exception as exc:
        return [f"{path}: {exc}"]


def _validate_modified_files(base_dir: Path, modified_paths: list[str]) -> list[str]:
    """Syntax-check all modified .py files.  Returns list of errors (empty = pass)."""
    errors: list[str] = []
    for rel in modified_paths:
        p = base_dir / rel
        if p.suffix == ".py" and p.is_file():
            errors.extend(_validate_python_syntax(p))
    return errors


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


# ── M7-9: Structured commit message ──────────────────────────────────────────

def _make_commit_message(task_id: str, task_title: str) -> str:
    """Return a commit message in the canonical format:
       [arbiter-self-build] <task_id>: <task_title>
    """
    return f"[arbiter-self-build] {task_id}: {task_title}\n\nCo-authored-by: Arbiter <arbiter@bot>"


def _git_commit(base_dir: Path, task_id: str, task_title: str) -> bool:
    """Stage all changes and commit with the structured self-build message."""
    msg = _make_commit_message(task_id, task_title)
    try:
        subprocess.run(["git", "add", "-A"], cwd=str(base_dir), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", msg], cwd=str(base_dir), check=True, capture_output=True)
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


# ── M7-1: SelfBuildController ─────────────────────────────────────────────────

class SelfBuildController:
    """Orchestrates the full autonomous self-build cycle (M7-1).

    One controller is long-lived per server process.  Call ``run_cycle()`` to
    execute a single task end-to-end according to the configured autonomy mode.

    Autonomy modes (M7-2):
      - ``manual``   – Return next task info; take no action.
      - ``assist``   – Generate code patch; pause for human approval before applying.
      - ``semiauto`` – Apply patch automatically; pause for approval before commit.
      - ``fullauto`` – Plan → code → validate → test → commit without interruption.
    """

    def __init__(self, base_dir: Path, llm: Any, roadmap_file: Path | None = None) -> None:
        self.base_dir = base_dir
        self.llm = llm
        self._roadmap_file = roadmap_file or (base_dir / "workspace" / "roadmap.json")
        # Approval event set by the REST endpoint when the user approves/rejects
        self._approval_event: asyncio.Event = asyncio.Event()
        self._approval_result: bool = True
        # Last generated patch (for Assist-mode display)
        self.pending_patch: str = ""
        self.pending_task: dict[str, Any] | None = None

    # ── Public API ─────────────────────────────────────────────────────────────

    async def run_cycle(
        self,
        emit: Callable[[str], None],
        mode: str = "assist",
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Run one self-build cycle for a task.  Returns a result dict."""
        if not self._roadmap_file.is_file():
            emit("❌ roadmap.json not found\n")
            return {"status": "error", "error": "roadmap.json not found"}

        # ── M7-2: Manual mode ──────────────────────────────────────────────────
        if mode == "manual":
            task, ms = _roadmap_next(self._roadmap_file)
            if task is None:
                emit("🎉 All roadmap tasks are complete!\n")
                return {"status": "complete"}
            emit(f"📋 Next task: [{task['id']}] {task.get('title', '')}\n")
            if task.get("description"):
                emit(f"   {task['description']}\n")
            return {
                "status": "manual",
                "next_task": task,
                "milestone": ms.get("title") if ms else None,
            }

        # ── Resolve task ───────────────────────────────────────────────────────
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
        task_desc  = task.get("description", "")

        emit(f"🤖 [arbiter-self-build] {task_id} — {task_title}\n")

        if task.get("review_required"):
            emit("⚠️  Task requires human review — skipping auto-build\n")
            return {"status": "skipped", "reason": "review_required", "task_id": task_id}

        # Mark task as in_progress so the UI reflects current work
        await asyncio.get_event_loop().run_in_executor(
            None, _mark_task_in_progress, self._roadmap_file, task_id
        )

        # ── M7-3: Task planning step ───────────────────────────────────────────
        emit("📐 Planning implementation steps…\n")
        plan = await self._generate_plan(task_id, task_title, task_desc)
        emit(f"📋 Plan:\n{plan}\n\n")

        # ── M7-4: File identification ──────────────────────────────────────────
        emit("🔍 Identifying files to create or modify…\n")
        source_ctx = await asyncio.get_event_loop().run_in_executor(
            None, _collect_source_files, self.base_dir
        )
        target_files = await self._identify_files(task_id, task_title, task_desc, plan, source_ctx)
        emit(f"📁 Target files: {target_files}\n\n")

        # ── M7-8: Iteration loop ───────────────────────────────────────────────
        loop_log: list[str] = []
        attempt = 0
        committed = False

        while attempt < SelfBuildLoop.MAX_RETRIES:
            attempt += 1
            emit(f"\n── Attempt {attempt}/{SelfBuildLoop.MAX_RETRIES} ──\n")

            # ── M7-5: Code generation ──────────────────────────────────────────
            emit("🧠 Generating code patch…\n")
            try:
                patch_text = await self._generate_patch(
                    task_id, task_title, task_desc, plan, source_ctx, target_files
                )
            except Exception as exc:
                emit(f"❌ LLM error: {exc}\n")
                loop_log.append(f"attempt {attempt}: LLM error: {exc}")
                continue

            if not patch_text.strip():
                emit("⚠️  LLM returned empty patch — skipping\n")
                loop_log.append(f"attempt {attempt}: empty patch")
                break

            # Safety: check for blocked files
            blocked = [
                f for f in re.findall(r"^\+\+\+ b/(.+)$", patch_text, re.MULTILINE)
                if f.strip() in BLOCKED_FILES
            ]
            if blocked:
                emit(f"🚫 Patch touches blocked files: {blocked} — aborting\n")
                loop_log.append(f"attempt {attempt}: blocked files {blocked}")
                break

            # ── M7-2: Assist mode — ask for approval before applying ───────────
            if mode == "assist":
                emit("⏳ Assist mode: patch generated. Waiting for approval…\n")
                self.pending_patch = patch_text
                self.pending_task  = {"task_id": task_id, "task_title": task_title}
                approved = await self._wait_for_approval()
                self.pending_patch = ""
                self.pending_task  = None
                if not approved:
                    emit("✕ Patch rejected by user.\n")
                    loop_log.append(f"attempt {attempt}: rejected by user (assist)")
                    break
                emit("✅ Patch approved.\n")

            # ── Apply patch ────────────────────────────────────────────────────
            emit("🔧 Applying patch…\n")
            try:
                modified = await asyncio.get_event_loop().run_in_executor(
                    None, _apply_patch, self.base_dir, patch_text
                )
                emit(f"   Modified: {modified}\n")
            except Exception as exc:
                emit(f"❌ Patch failed: {exc}\n")
                loop_log.append(f"attempt {attempt}: patch apply error: {exc}")
                await asyncio.get_event_loop().run_in_executor(None, _git_rollback, self.base_dir)
                continue

            # ── M7-6: Syntax validation ────────────────────────────────────────
            emit("🔍 Validating syntax…\n")
            syntax_errors = await asyncio.get_event_loop().run_in_executor(
                None, _validate_modified_files, self.base_dir, modified
            )
            if syntax_errors:
                emit("❌ Syntax errors found:\n" + "\n".join(f"   {e}" for e in syntax_errors) + "\n")
                loop_log.append(f"attempt {attempt}: syntax errors: {syntax_errors}")
                await asyncio.get_event_loop().run_in_executor(None, _git_rollback, self.base_dir)
                continue
            emit("✅ Syntax OK\n")

            # ── M7-7: Test execution ───────────────────────────────────────────
            emit("🧪 Running tests…\n")
            passed, test_output = await asyncio.get_event_loop().run_in_executor(
                None, _run_tests, self.base_dir, 120
            )
            emit(test_output[-2000:] + "\n")

            if not passed:
                emit(f"❌ Tests failed (attempt {attempt})\n")
                loop_log.append(f"attempt {attempt}: tests failed")
                await asyncio.get_event_loop().run_in_executor(None, _git_rollback, self.base_dir)
                continue

            emit("✅ Tests passed!\n")

            # ── M7-2: SemiAuto mode — ask for approval before commit ───────────
            if mode == "semiauto":
                emit("⏳ SemiAuto mode: changes applied and tested. Waiting for approval to commit…\n")
                self.pending_task = {"task_id": task_id, "task_title": task_title}
                approved = await self._wait_for_approval()
                self.pending_task = None
                if not approved:
                    emit("✕ Commit rejected by user — rolling back.\n")
                    loop_log.append(f"attempt {attempt}: commit rejected (semiauto)")
                    await asyncio.get_event_loop().run_in_executor(None, _git_rollback, self.base_dir)
                    break
                emit("✅ Commit approved.\n")

            # ── M7-9: Structured git commit ────────────────────────────────────
            committed = await asyncio.get_event_loop().run_in_executor(
                None, _git_commit, self.base_dir, task_id, task_title
            )
            if committed:
                emit(f"📦 Committed: [arbiter-self-build] {task_id}: {task_title}\n")

            # ── M7-10: Roadmap update ──────────────────────────────────────────
            notes = (
                f"Auto-built in {attempt} attempt(s). "
                f"Mode: {mode}. Files: {', '.join(modified) if modified else 'none'}."
            )
            await asyncio.get_event_loop().run_in_executor(
                None, _mark_task_done, self._roadmap_file, task_id, notes
            )
            emit(f"🏁 Task {task_id} marked done in roadmap!\n")
            loop_log.append(f"attempt {attempt}: SUCCESS")
            break

        # ── Telemetry (M7-15) ──────────────────────────────────────────────────
        telem = _load_telemetry(self.base_dir)
        entry: dict[str, Any] = {
            "task_id": task_id, "task_title": task_title,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "mode": mode, "attempts": attempt,
            "success": committed, "log": loop_log,
        }
        telem.append(entry)
        await asyncio.get_event_loop().run_in_executor(None, _save_telemetry, self.base_dir, telem)

        return {
            "status": "success" if committed else "failed",
            "task_id": task_id, "task_title": task_title,
            "mode": mode, "attempts": attempt, "commit": committed,
            "log": loop_log,
        }

    # ── Approval helpers (M7-2) ────────────────────────────────────────────────

    async def _wait_for_approval(self, timeout: float = 300.0) -> bool:
        """Suspend until the REST approve endpoint signals a decision."""
        self._approval_event.clear()
        try:
            await asyncio.wait_for(self._approval_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Approval timed out after %.0f s — treating as rejected", timeout)
            return False
        return self._approval_result

    def set_approval(self, approved: bool) -> None:
        """Called by the REST endpoint to resolve a pending approval."""
        self._approval_result = approved
        self._approval_event.set()

    # ── LLM helpers ───────────────────────────────────────────────────────────

    async def _llm_chat(self, messages: list[dict]) -> str:
        return await asyncio.get_event_loop().run_in_executor(
            None, lambda: self.llm.chat(messages)
        )

    async def _generate_plan(self, task_id: str, task_title: str, task_desc: str) -> str:
        """M7-3: Ask the LLM for a numbered step-by-step implementation plan."""
        system = (
            "You are a senior software engineer planning an implementation for Arbiter Engine.\n"
            "Produce a concise numbered list of implementation steps (5–10 items).\n"
            "Each step should be a single short sentence. Output ONLY the numbered list."
        )
        user = f"Task ID: {task_id}\nTitle: {task_title}\nDescription: {task_desc}"
        try:
            return await self._llm_chat([
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ])
        except Exception as exc:
            logger.warning("Plan generation failed: %s", exc)
            return f"1. Implement {task_title}"

    async def _identify_files(
        self,
        task_id: str, task_title: str, task_desc: str,
        plan: str, source_ctx: str,
    ) -> list[str]:
        """M7-4: Ask the LLM which files need to be created or modified."""
        system = (
            "You are a senior software engineer identifying files for a code change.\n"
            "Given the task and the current source tree, list the relative file paths\n"
            "that need to be created or modified.  Output ONLY one path per line.\n"
            "Do NOT include: " + ", ".join(sorted(BLOCKED_FILES))
        )
        user = (
            f"Task: {task_id} — {task_title}\n"
            f"Plan:\n{plan}\n\n"
            f"Current source (excerpts):\n{source_ctx[:4000]}"
        )
        try:
            raw = await self._llm_chat([
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ])
            paths = [
                line.strip().lstrip("/")
                for line in raw.splitlines()
                if line.strip() and not line.strip().startswith("#")
                   and line.strip() not in BLOCKED_FILES
            ]
            return paths[:15]  # cap at 15 files
        except Exception as exc:
            logger.warning("File identification failed: %s", exc)
            return []

    async def _generate_patch(
        self,
        task_id: str, task_title: str, task_desc: str,
        plan: str, source_ctx: str, target_files: list[str],
    ) -> str:
        """M7-5: Ask the LLM to generate a unified diff patch."""
        system = (
            "You are a senior software engineer implementing a feature for Arbiter Engine.\n"
            "Produce a valid unified diff (patch -p1 compatible) that implements the task.\n"
            "Rules:\n"
            "  - Output ONLY the diff, no explanation, no markdown fences.\n"
            "  - Do NOT modify: " + ", ".join(sorted(BLOCKED_FILES)) + "\n"
            "  - Keep changes minimal and targeted.\n"
            "  - Ensure all Python files are syntactically valid.\n"
        )
        files_hint = f"Target files:\n" + "\n".join(f"  - {f}" for f in target_files) if target_files else ""
        user = (
            f"Task ID: {task_id}\nTask Title: {task_title}\nTask Description: {task_desc}\n\n"
            f"Implementation plan:\n{plan}\n\n"
            f"{files_hint}\n\n"
            f"Current source files (excerpts):\n{source_ctx[:_MAX_SOURCE_CHARS]}"
        )
        raw = await self._llm_chat([
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ])
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            inner = lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:]
            raw = "\n".join(inner)
        return raw


# ── Legacy SelfBuildLoop (backward compat) ────────────────────────────────────

class SelfBuildLoop:
    """Backward-compatible wrapper around SelfBuildController.

    Retained so that existing server.py code that creates ``SelfBuildLoop``
    continues to work while new code can use ``SelfBuildController`` directly.
    """

    MAX_RETRIES = 3

    def __init__(self, base_dir: Path, llm: Any) -> None:
        self.base_dir = base_dir
        self.llm = llm
        self._roadmap_file = base_dir / "workspace" / "roadmap.json"
        self._controller = SelfBuildController(base_dir, llm, self._roadmap_file)

    async def run(self, emit: Callable[[str], None], task_id: str | None = None) -> dict[str, Any]:
        return await self._controller.run_cycle(emit, mode="fullauto", task_id=task_id)

    def set_approval(self, approved: bool) -> None:
        self._controller.set_approval(approved)


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
