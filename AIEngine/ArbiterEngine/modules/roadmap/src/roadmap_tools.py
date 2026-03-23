"""Roadmap module — read and update the SwissAgent self-development roadmap."""
from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _roadmap_path() -> Path:
    """Return the canonical path of roadmap.json inside workspace/."""
    root = Path(__file__).resolve().parents[3]
    workspace = root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace / "roadmap.json"


def _load() -> dict[str, Any]:
    p = _roadmap_path()
    if not p.exists():
        return {"milestones": []}
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict[str, Any]) -> None:
    p = _roadmap_path()
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _all_tasks(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Yield all tasks across all milestones with their milestone_id attached."""
    tasks = []
    for ms in data.get("milestones", []):
        for t in ms.get("tasks", []):
            tasks.append({**t, "_milestone_id": ms["id"], "_milestone_title": ms["title"]})
    return tasks


# ── Public tool functions ──────────────────────────────────────────────────────

def roadmap_list(status_filter: str = "all") -> dict[str, Any]:
    """Return the full roadmap, optionally filtered by task status."""
    data = _load()
    valid = {"pending", "in_progress", "done", "blocked", "all"}
    if status_filter not in valid:
        return {"error": f"Invalid status_filter. Use one of: {sorted(valid)}"}

    out_milestones = []
    for ms in data.get("milestones", []):
        tasks = ms.get("tasks", [])
        if status_filter != "all":
            tasks = [t for t in tasks if t.get("status") == status_filter]
        counts = {
            "total": len(ms.get("tasks", [])),
            "done": sum(1 for t in ms.get("tasks", []) if t.get("status") == "done"),
            "in_progress": sum(1 for t in ms.get("tasks", []) if t.get("status") == "in_progress"),
            "pending": sum(1 for t in ms.get("tasks", []) if t.get("status") == "pending"),
        }
        out_milestones.append({
            "id": ms["id"],
            "title": ms["title"],
            "description": ms.get("description", ""),
            "status": ms.get("status", "pending"),
            "counts": counts,
            "tasks": tasks,
        })

    total_tasks = sum(ms["counts"]["total"] for ms in out_milestones)
    done_tasks = sum(ms["counts"]["done"] for ms in out_milestones)

    return {
        "project": data.get("project", "SwissAgent"),
        "version": data.get("version", "0.1.0"),
        "progress": f"{done_tasks}/{total_tasks} tasks complete",
        "milestones": out_milestones,
    }


def roadmap_next_task() -> dict[str, Any]:
    """Return the highest-priority next task to work on."""
    data = _load()
    all_tasks = _all_tasks(data)

    # Priority order: in_progress first, then pending; higher priority first
    priority_order = {"high": 0, "medium": 1, "low": 2}

    candidates = [t for t in all_tasks if t.get("status") in ("in_progress", "pending")]
    if not candidates:
        return {
            "task": None,
            "message": "🎉 All tasks are complete! Add new tasks with roadmap_add_task.",
        }

    candidates.sort(
        key=lambda t: (
            0 if t.get("status") == "in_progress" else 1,
            priority_order.get(t.get("priority", "medium"), 1),
        )
    )
    task = candidates[0]
    return {
        "task": task,
        "message": (
            f"Next task: [{task['id']}] {task['title']} "
            f"(milestone: {task['_milestone_title']}, priority: {task.get('priority','medium')})"
        ),
        "prompt_suggestion": (
            f"Work on roadmap task [{task['id']}]: {task['title']}.\n"
            f"Description: {task.get('description','')}\n"
            "When done, call roadmap_complete_task to mark it finished."
        ),
    }


def roadmap_start_task(task_id: str) -> dict[str, Any]:
    """Mark a task as in_progress."""
    data = _load()
    for ms in data.get("milestones", []):
        for t in ms.get("tasks", []):
            if t["id"] == task_id:
                t["status"] = "in_progress"
                t["started_at"] = datetime.now(timezone.utc).isoformat()
                _save(data)
                return {"success": True, "task_id": task_id, "status": "in_progress"}
    return {"error": f"Task '{task_id}' not found"}


def roadmap_complete_task(task_id: str, notes: str = "") -> dict[str, Any]:
    """Mark a task as done and optionally record notes."""
    data = _load()
    for ms in data.get("milestones", []):
        for t in ms.get("tasks", []):
            if t["id"] == task_id:
                t["status"] = "done"
                t["completed_at"] = datetime.now(timezone.utc).isoformat()
                if notes:
                    t["notes"] = notes
                # Auto-update milestone status
                all_done = all(x.get("status") == "done" for x in ms["tasks"])
                any_in_progress = any(x.get("status") == "in_progress" for x in ms["tasks"])
                ms["status"] = "done" if all_done else ("in_progress" if any_in_progress else ms.get("status", "pending"))
                _save(data)
                next_result = roadmap_next_task()
                return {
                    "success": True,
                    "task_id": task_id,
                    "status": "done",
                    "notes_saved": bool(notes),
                    "next_task": next_result.get("task"),
                    "next_message": next_result.get("message", ""),
                }
    return {"error": f"Task '{task_id}' not found"}


def roadmap_add_task(
    milestone_id: str,
    title: str,
    description: str = "",
    priority: str = "medium",
) -> dict[str, Any]:
    """Add a new task to an existing milestone."""
    valid_priorities = {"high", "medium", "low"}
    if priority not in valid_priorities:
        priority = "medium"

    data = _load()
    for ms in data.get("milestones", []):
        if ms["id"] == milestone_id:
            # Generate a unique task ID within the milestone
            existing_ids = {t["id"] for t in ms.get("tasks", [])}
            n = len(ms.get("tasks", [])) + 1
            task_id = f"{milestone_id.replace('m', 't')}-{n}"
            while task_id in existing_ids:
                task_id = f"{milestone_id.replace('m', 't')}-{uuid.uuid4().hex[:4]}"

            new_task = {
                "id": task_id,
                "title": title,
                "description": description,
                "status": "pending",
                "priority": priority,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            ms.setdefault("tasks", []).append(new_task)
            _save(data)
            return {
                "success": True,
                "task": new_task,
                "milestone": ms["title"],
                "message": f"Task '{title}' added to milestone '{ms['title']}' with id '{task_id}'.",
            }
    return {"error": f"Milestone '{milestone_id}' not found"}
