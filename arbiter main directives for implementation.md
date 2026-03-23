# Arbiter — Implementation Directives

**Version:** 1.0  
**Date:** 2026-03-23  
**Applies to:** All contributors and self-build agents

---

## Purpose

This document provides concrete implementation directives for building Arbiter's three pillars. It is the reference for anyone (human or Arbiter self-build agent) implementing a roadmap task.

---

## Implementation Order

Priority from highest to lowest:

1. Complete **M2** (Arbiter Engine) and **M3** (Archive) in-progress tasks
2. Build **M6** (Visual Studio Integration) — new highest priority
3. Complete **M4** (WPF IDE) finishing touches
4. Build **M7** (Self-Iteration) full pipeline
5. Build **M5** (Advanced Chat) capabilities
6. Build **M8** (Distribution) for release

---

## Pillar 1 — Chat Engine Implementation

### Directive: All Chat Features Must Share Context

Every chat message sent to `/chat` or `/assistant/chat` must include:

1. **Project name** — which project the user is working on
2. **File context** — path and content of the currently open file (if any)
3. **Selection** — selected text from the editor (if any)
4. **Conversation history** — last N messages from SQLite (configurable, default 20)
5. **Archive context** — top 3 relevant Archive entries matching the query (M5+)

The Python bridge injects these into the LLM system prompt automatically. Clients only need to pass `project`, `file_context`, and `selection` in the request body.

### Directive: Streaming is Required

All AI responses must stream via WebSocket or Server-Sent Events. Blocking single-response endpoints are only for compatibility. New chat features MUST use streaming.

### Directive: Slash Commands Format

Slash commands are detected server-side in `fastapi_bridge.py`. Pattern: `^/(\w+)\s*(.*)`.

| Command | Handler | Notes |
|---------|---------|-------|
| `/build` | Calls `/build` endpoint, streams output to chat | M5 |
| `/run` | Calls `/run` endpoint | M5 |
| `/test` | Calls `/test` endpoint | M5 |
| `/commit <msg>` | Calls `/git/commit` endpoint | M5 |
| `/push` | Calls `/git/push` endpoint | M5 |
| `/branch <name>` | Calls `/git/branch/create` endpoint | M5 |
| `/task <desc>` | Creates a task in `Projects/<project>/roadmap.json` | M5 |
| `/search <term>` | Queries `/archive/search`, injects results into next message | M5 |
| `/agent <goal>` | Routes to `/assistant/chat/agentic` | M5 |
| `/save snippet <name>` | Saves last code block to `Memory/snippets.json` | M5 |

### Directive: Code Block Actions

When an AI response contains a fenced code block (` ``` `), the frontend MUST render action buttons:
- **Apply** — writes the code to the currently open file (or asks for a path if none open)
- **Copy** — copies to clipboard
- **Save Snippet** — saves to `Memory/snippets.json` with a user-provided name
- **Diff** — shows a diff preview if applying to an existing file

### Directive: Persona Persistence

The active persona for each project is stored in the project's SQLite database table `project_settings`. It must survive app restarts. When switching projects, the persona is loaded from the database — not from a global config.

---

## Pillar 2 — Visual Studio Integration Implementation

### Directive: VSIX Project Location

The VSIX project lives in `VisualStudioExtension/` at the repository root. It is a C# project targeting Visual Studio 2022 SDK. It references `Microsoft.VisualStudio.SDK` via NuGet.

### Directive: Chat Panel Uses WebView2

The `ChatToolWindow` hosts a WebView2 control that loads the Arbiter chat UI from the running backend (`http://127.0.0.1:8000/gui/`). This reuses the existing Monaco IDE chat panel without rebuilding it. The WebView2 host handles bidirectional messaging for VS-specific context (active document, selection, build events).

### Directive: Context Injection via PostMessage

When the user opens a file in VS, the `DocumentEvents.DocumentOpened` handler posts a message to the WebView2:

```csharp
chatWebView.CoreWebView2.PostWebMessageAsJson(JsonSerializer.Serialize(new {
    type = "vs_context_update",
    payload = new {
        filePath = document.FullName,
        language = Path.GetExtension(document.FullName).TrimStart('.')
    }
}));
```

The chat UI's JavaScript handles `vs_context_update` and injects the file path into the next chat message.

### Directive: AI Commands Use the /ai/action Endpoint

All VS commands (Ask, Explain, Fix, Refactor, Tests, Docs) POST to `/ai/action` with:

```json
{
  "action": "explain",
  "code": "<selected text or full file>",
  "language": "csharp",
  "file_path": "C:\\MyProject\\Login.cs"
}
```

The response is displayed in the chat tool window or in a modal dialog, depending on command type.

### Directive: Build Error Integration

After a VS build fails, the `BuildEvents.OnBuildDone` handler collects all errors from the Error List and POSTs to `/ai/action`:

```json
{
  "action": "fix_errors",
  "errors": [
    {
      "code": "CS0246",
      "message": "The type or namespace name 'ILoginService' could not be found",
      "file": "Login.cs",
      "line": 12
    }
  ],
  "project_path": "C:\\MyProject"
}
```

The AI returns fix suggestions that appear in a custom Error List column "Arbiter Fix".

### Directive: Settings Page Values

The `ArbiterOptionsPage` (Tools → Options → Arbiter) persists these settings in VS user settings:

```csharp
[DesignerSerializationVisibility(DesignerSerializationVisibility.Visible)]
[Category("Connection")]
public string BackendUrl { get; set; } = "http://127.0.0.1:8000";

[Category("AI")]
public string DefaultPersona { get; set; } = "Arbiter";

[Category("Voice")]
public bool EnableVoice { get; set; } = false;

[Category("Self-Build")]
public string SelfBuildMode { get; set; } = "Assist";
```

---

## Pillar 3 — Self-Iteration Implementation

### Directive: Self-Build Loop Lives in ArbiterEngine

The `SelfBuildController` is a Python class in `AIEngine/ArbiterEngine/core/self_build.py`. The REST API is exposed by `server.py` at `/self-build/*`. The WPF and VS extension UIs call these endpoints.

### Directive: Roadmap Task Selection Algorithm

```python
def select_next_task(roadmap: dict) -> Optional[dict]:
    for milestone in roadmap["milestones"]:
        if milestone["status"] in ("done", "pending"):
            continue
        for task in milestone["tasks"]:
            if task["status"] == "in_progress":
                return {"milestone": milestone["id"], "task": task}
    for milestone in roadmap["milestones"]:
        if milestone["status"] == "done":
            continue
        for task in milestone["tasks"]:
            if task["status"] == "pending":
                return {"milestone": milestone["id"], "task": task}
    return None  # All done
```

### Directive: Generated Code Validation

Before applying any AI-generated code change:

1. **Python files**: Run `ast.parse(content)` — reject if SyntaxError
2. **C# files**: Run `dotnet build --no-restore` in a temp directory — reject if non-zero exit
3. **JSON files**: Run `json.loads(content)` — reject if ValueError
4. **TypeScript/JavaScript files**: Run `node --check <file>` — reject if non-zero exit

If validation fails, the AI gets the error message and regenerates. Maximum 3 attempts before requesting human review.

### Directive: Commit Message Format

All self-build commits MUST use this format:

```
[arbiter-self-build] <milestone-id>-<task-id>: <task title>

<bullet list of files created/modified>

Roadmap: <task-id> → done
Self-build mode: <Manual|Assist|SemiAuto|FullAuto>
```

### Directive: Self-Build Does Not Modify Protected Files

In any autonomy mode above Manual, the self-build loop MUST refuse to modify:

- `HostApp/Config/settings.json`
- `AIEngine/ArbiterEngine/configs/config.toml`
- `.env`
- `*.vsixmanifest`
- `.gitignore`
- `Arbiter.sln`
- Any file in `.git/`

Attempting to modify a protected file triggers a human approval request regardless of mode.

### Directive: Approval Flow (Assist and SemiAuto)

1. Self-build generates changes and stores them as a diff in `logs/self_build/<task-id>.diff`
2. Sets `self_build_state.pending_change = True`
3. Notifies the chat panel and IDE panel (WebSocket push)
4. Waits for `POST /self-build/approve` or `POST /self-build/reject`
5. On approve: applies diff, runs tests, commits
6. On reject: AI receives rejection reason and generates alternative

---

## API Parity Rule

**Any new API endpoint added to `fastapi_bridge.py` MUST also be added to `server.py`** with identical request/response schema. Both files import from the same helper modules to avoid code duplication. If a feature is too complex for the lightweight bridge, add a stub that returns `{"status": "not_available", "mode": "lightweight"}`.

---

## Code Style Directives

### Python

- All public functions have docstrings
- Type annotations required on all function signatures
- No bare `except:` — always catch specific exceptions
- All new endpoints return `{"status": "ok", ...}` on success and `{"status": "error", "detail": "..."}` on failure
- Log all AI calls with `logger.info(f"[chat] project={project} tokens={tokens_used}")`

### C# (WPF + VSIX)

- All `async` methods return `Task` or `Task<T>`
- All `WebView2` operations check `CoreWebView2 != null` before use
- All UI updates on background threads use `Application.Current.Dispatcher.InvokeAsync`
- All VSIX components are `AsyncPackage`-based — no synchronous package loading

### Documentation

- `README.md` is the public-facing document — keep it accurate and concise
- `Repo Directive.md` is the architecture and direction guide — update when direction changes
- `Specs.md` is the technical reference — update when API contracts or data formats change
- `roadmap.json` is the source of truth for task status — update after every completed task

---

## Testing Directives

- Python: all new modules in `PythonBridge/` or `ArbiterEngine/` have a `tests/test_<module>.py` file
- C#: all new WPF utility classes have an xUnit test in `HostApp.Tests/`
- VSIX: integration tests use the VS Extensibility SDK test framework
- Self-build: any AI-generated code must pass the project's test suite before commit

---

## Git Directives

- Branch naming: `feature/<milestone-id>-<short-description>` (e.g., `feature/M6-vsix-chat-panel`)
- PR title format: `[M6] Add Arbiter chat tool window to VS extension`
- AI self-build commits: `[arbiter-self-build] M7-3: Task planning implementation`
- Never force-push to `main`
- All PRs require passing tests before merge
