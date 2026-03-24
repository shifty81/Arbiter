# Self-Build Loop

The self-build loop is Arbiter's autonomous self-improvement system. It reads
`roadmap.json`, picks the next pending task, generates a plan, writes code,
tests it, and commits — then repeats.

---

## Overview

```
roadmap.json (next pending task)
       │
       ▼
SelfBuildController.start(mode)
       │
       ▼
Phase 1 — Plan
  AI reads task description + relevant file context
  AI outputs numbered step-by-step implementation plan
       │
       ▼
Phase 2 — Identify Files
  AI identifies which files to create or modify
  List returned as JSON array of file paths
       │
       ▼
Phase 3 — Generate Code
  For each file: AI writes a unified diff patch
  Patches stored in .arbiter/self_build_log.json
       │
       ▼
Phase 4 — Validate
  Python: AST parse check
  C#: dotnet build dry-run
  If validation fails → retry (up to 3×)
       │
       ▼
Phase 5 — Approval (Assist / SemiAuto only)
  Diff presented to user for review
  User approves or rejects
  FullAuto: skipped
       │
       ▼
Phase 6 — Apply
  Patches applied to filesystem
       │
       ▼
Phase 7 — Test
  pytest / dotnet test / npm test (auto-detected)
  Failures trigger retry loop
       │
       ▼
Phase 8 — Commit
  git add + git commit with [arbiter-self-build] M<n>-<t>: <title>
       │
       ▼
Phase 9 — Update Roadmap
  roadmap.json task status set to "done"
  version incremented
       │
       ▼
Loop continues to next pending task
```

---

## Autonomy Modes

| Mode | Description | Approval Required |
|------|-------------|-------------------|
| `manual` | Loop is disabled; all code is user-initiated | N/A |
| `assist` | Loop generates a plan and diff; user must approve each patch before applying | Yes (every patch) |
| `semiauto` | Loop applies patches automatically; user approves the final commit | Yes (commit) |
| `fullauto` | Fully autonomous — plans, codes, tests, commits without any prompts | No |

**Recommended for first use:** `assist` mode — you stay in control and can learn
how Arbiter works before enabling higher autonomy levels.

---

## REST API

```http
POST /self-build/start
Body: { "mode": "assist" | "semiauto" | "fullauto" }

POST /self-build/stop

GET  /self-build/status
Response: {
  "running": true,
  "mode": "assist",
  "current_task": "M10-1",
  "phase": "generate",
  "loop_count": 3
}

POST /self-build/approve
Body: { "session_id": "..." }

POST /self-build/reject
Body: { "session_id": "...", "reason": "..." }

GET  /self-build/log
Response: [ { "task_id": "...", "diffs": [...], "status": "..." }, ... ]

GET  /self-build/roadmap
Response: <full roadmap.json content>
```

---

## Safety Constraints

The self-build loop operates under strict safety rules to prevent runaway changes:

| Constraint | Detail |
|------------|--------|
| Protected files | `config.toml`, `.env`, `settings.json` are never modified in FullAuto |
| Max tasks per session | Configurable; default 5 (prevents infinite loops) |
| Max retries per task | 3 — if generation still fails, task is marked `blocked` |
| Never pushes to remote | All commits are local; no `git push` without explicit user action |
| Diffs stored before apply | Every patch is saved to `.arbiter/self_build_log.json` for audit |
| Test gate | Code that fails tests is never committed |

---

## Roadmap Format

`roadmap.json` is the source of truth for the self-build loop. The loop reads
only `status: "pending"` tasks in milestone order.

```json
{
  "milestones": [
    {
      "id": "M10",
      "title": "Enhanced Chat & AI",
      "status": "in_progress",
      "tasks": [
        { "id": "M10-1", "title": "Chat session branching", "status": "done" },
        { "id": "M10-2", "title": "Conversation templates", "status": "pending" }
      ]
    }
  ]
}
```

---

## Monitoring in the IDE

The Monaco IDE includes a **Self-Build Loop** panel (sidebar → AI & Chat → Self-Build Loop)
that shows:

- Current task and phase
- Live plan text
- Diff preview
- Approve / Reject buttons (Assist/SemiAuto mode)
- Session log

The Visual Studio extension also has a **Self-Build** tool window
(View → Other Windows → Arbiter Self-Build).

---

## Commit Message Format

All self-build commits follow this format:

```
[arbiter-self-build] M10-2: Conversation templates

Phase: commit
Task: M10-2
Milestone: M10 — Enhanced Chat & AI
Mode: semiauto
Files: server.py, gui/index.html
```

This makes them easily distinguishable from human commits in `git log`.

---

## Extending the Roadmap

To add new tasks for Arbiter to implement, edit `roadmap.json`:

```json
{
  "id": "M15-1",
  "title": "My new feature",
  "description": "Detailed description of what to build and how",
  "status": "pending",
  "files_hint": ["server.py", "gui/index.html"],
  "acceptance_criteria": [
    "New endpoint /my/endpoint responds with 200",
    "All existing tests still pass"
  ]
}
```

The more detail you provide in `description` and `acceptance_criteria`, the
better the generated code will be.
