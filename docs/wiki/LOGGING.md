# Logging

Arbiter uses a two-tier logging strategy:

1. **System logs** — rotating plain-text log files per subsystem, written to
   `<repo_root>/logs/<system>/` so all logs are aggregated in one place.
2. **Workspace logs** — structured JSONL logs per project workspace, written to
   `<project>/.arbiter/logs/workspace.jsonl` for per-session traceability.

---

## System Log Locations

All system-level logs are written to the `logs/` directory at the repository root.
Each subsystem has its own subdirectory to prevent log interleaving:

```
<repo_root>/logs/
├── arbiter_engine/
│   └── arbiter_engine.log      ← ArbiterEngine (server.py, port 8001)
├── python_bridge/
│   └── python_bridge.log       ← PythonBridge (fastapi_bridge.py, port 8000)
├── host_app/
│   └── host_app.log            ← WPF HostApp events forwarded via the bridge
├── vs_extension/
│   └── vs_extension.log        ← Visual Studio extension events
└── self_build/
    └── self_build.log          ← Autonomous self-build loop activity
```

All log files use rotating file handlers with a maximum size of **5 MB** per file
and **5 backup copies** retained. Logs are UTF-8 encoded.

### Log Format

```
2026-03-24 01:17:26 [INFO    ] arbiter.engine: Server started on port 8001
2026-03-24 01:17:26 [DEBUG   ] arbiter.self_build: Reading roadmap.json
2026-03-24 01:17:26 [WARNING ] arbiter.python_bridge: LLM backend offline, retrying
2026-03-24 01:17:27 [ERROR   ] arbiter.engine: Model load failed: FileNotFoundError
```

---

## Workspace Structured Logs (JSONL)

Per-project structured logs are stored in JSONL format (one JSON object per line):

**Location:** `<project_dir>/.arbiter/logs/workspace.jsonl`

**Entry format:**

```json
{
  "timestamp": "2026-03-24T01:17:26.713Z",
  "level": "INFO",
  "source": "self_build",
  "message": "Task M10-1 completed successfully",
  "extra": {
    "task_id": "M10-1",
    "files_modified": ["server.py", "roadmap.json"],
    "duration_s": 12.4
  }
}
```

**Log levels:** `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRASH`

### Reading Workspace Logs

Via the REST API:

```http
GET /logs/workspace?level=ERROR&limit=50
```

Via Python (internal):

```python
from core.logger import read_workspace_log

entries = read_workspace_log("/path/to/project", level="ERROR", limit=50)
for entry in entries:
    print(entry["timestamp"], entry["message"])
```

---

## Crash Capture

When an unhandled exception occurs in the engine, it is automatically captured
and written to the workspace log with level `CRASH`:

```python
from core.logger import capture_crash

try:
    risky_operation()
except Exception as exc:
    capture_crash(workspace_path, exc, source="my_module")
```

The crash entry includes the full Python traceback in the `extra.traceback` field.
This is used by the local issues tracker to automatically file a crash report.

---

## Adding Logging to a New Subsystem

Use `setup_system_logging()` from `core/logger.py`:

```python
from core.logger import setup_system_logging

# Returns a namespaced logger that writes to logs/my_system/my_system.log
logger = setup_system_logging("my_system")
logger.info("My subsystem started")
```

For the PythonBridge (which lives in a separate package), use standard Python
logging configured to write to the same top-level `logs/` folder:

```python
import logging
import logging.handlers
from pathlib import Path

_log_dir = Path(__file__).parent.parent.parent / "logs" / "python_bridge"
_log_dir.mkdir(parents=True, exist_ok=True)
# ... configure RotatingFileHandler
```

---

## Log Viewer in Monaco IDE

The built-in Monaco IDE includes a **Log Viewer** accessible from:

- Sidebar → **Operations** → **Audit Log**

The viewer displays both system logs and workspace JSONL logs with filtering
by level, source, and time range.

---

## Log Rotation Policy

| Setting | Value |
|---------|-------|
| Max file size | 5 MB |
| Backup copies | 5 |
| Encoding | UTF-8 |
| Mode | Append |

When a log file reaches 5 MB it is rotated:
`arbiter_engine.log` → `arbiter_engine.log.1` → ... → `arbiter_engine.log.5`

---

## Troubleshooting Logging

**Logs not appearing in `logs/` folder:**
- Ensure the backend server has write permission to the repository directory
- Check if `roadmap.json` exists in the repo root (used by `_find_repo_root()`)
- If running from an unusual working directory, set `ARBITER_ROOT` env var

**Workspace log is empty:**
- The workspace log is only created after the first API call to a project
- Ensure the `.arbiter/logs/` directory is writable

**Log level too noisy:**
- Change `level` in `setup_logging()` call in `server.py` from `INFO` to `WARNING`
- Or set `ARBITER_LOG_LEVEL=WARNING` in your `.env` file
