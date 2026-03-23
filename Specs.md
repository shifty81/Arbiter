# Arbiter — Technical Specifications

**Version:** 1.0  
**Date:** 2026-03-23

---

## Overview

Arbiter is a three-pillar AI development platform:

1. **Chat Engine** (Pillar 1) — context-aware conversational assistant with full SDLC integration
2. **Visual Studio Integration** (Pillar 2) — native VSIX extension for Visual Studio 2022
3. **Self-Iteration** (Pillar 3) — autonomous self-build loop driven by `roadmap.json`

For full architecture details see `Repo Directive.md`. For the implementation roadmap see `roadmap.json`.

---

## Backend API Contract

Both backends (PythonBridge port 8000 and ArbiterEngine port 8001) implement the same API contract so all clients (WPF app, Monaco IDE, VS extension) work with either backend.

### Required Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check — returns `{"status": "ok"}` |
| `/status` | GET | GPU, VRAM, model, token limit, backend mode |
| `/llm/status` | GET | Active LLM backend: `gguf`, `ollama`, or `stub` |
| `/chat` | POST | Standard chat — `{message, project, use_voice, voice}` |
| `/assistant/chat` | POST | IDE-aware chat — adds file context to system prompt |
| `/assistant/chat/agentic` | POST | Triggers agentic plan→edit→test loop |
| `/history/{project}` | GET | Full conversation history for project |
| `/personas` | GET | List available personas |
| `/persona/{project}` | GET | Get active persona |
| `/persona/{project}` | POST | Set active persona — `{persona: "Coder"}` |
| `/files` | GET | List files in project directory |
| `/files/read` | POST | Read file — `{path}` |
| `/files/write` | POST | Write file — `{path, content}` |
| `/files/delete` | POST | Delete file — `{path}` |
| `/files/rename` | POST | Rename file — `{path, new_name}` |
| `/ai/complete` | POST | Code completion — `{code, language, cursor_line}` |
| `/ai/action` | POST | Code action — `{action, code, language}` |
| `/ai/propose` | POST | Propose change — returns diff + explanation |
| `/build` | POST | Build project — `{project_path}` |
| `/run` | POST | Run project — `{project_path}` |
| `/test` | POST | Test project — `{project_path}` |
| `/git/status` | GET | Working tree status |
| `/git/stage` | POST | Stage files |
| `/git/commit` | POST | Commit — `{message, author_name, author_email}` |
| `/git/log` | GET | Commit history |
| `/git/diff` | GET | File or commit diff |
| `/archive` | GET | Archive listing |
| `/archive/search` | GET | Keyword search — `?q=<term>` |
| `/archive/rebuild` | POST | Re-index all library folders |
| `/archive/export` | GET | Export as Markdown |
| `/library` | GET/POST/DELETE | Library path management |
| `/models` | GET | List recommended + downloaded models |
| `/models/download` | POST | Start async model download |
| `/stt` | POST | Speech-to-text — audio → text (Whisper) |
| `/self-build/start` | POST | Start self-build loop |
| `/self-build/stop` | POST | Stop self-build loop |
| `/self-build/status` | GET | Current task, progress, loop state |
| `/self-build/approve` | POST | Approve pending change (Assist/SemiAuto) |
| `/self-build/reject` | POST | Reject pending change |
| `/self-build/log` | GET | Full self-build session log |
| `/ws/run` | WebSocket | Streaming build output |
| `/ws/terminal` | WebSocket | Terminal output |
| `/ws/pty` | WebSocket | PTY terminal |

---

## Chat Request Format

```json
POST /chat
{
  "message": "Add error handling to my login function",
  "project": "MyProject",
  "use_voice": false,
  "voice": "British_Female",
  "file_context": "/path/to/login.py",
  "selection": "def login(user, password):\n    return db.check(user, password)"
}
```

## Chat Response Format

```json
{
  "response": "Here is the updated function with error handling...",
  "code_blocks": [
    {
      "language": "python",
      "content": "def login(user, password):\n    try:\n        ...",
      "filename": "login.py"
    }
  ],
  "persona": "Coder",
  "tokens_used": 412
}
```

---

## Persona System

Personas are defined in `persona_manager.py`. Each persona changes the system prompt injected before user messages.

| Persona | Style | Use Case |
|---------|-------|----------|
| Arbiter | Balanced, direct, professional | Default general purpose |
| Coder | Expert engineer, code-first | Code generation and review |
| Teacher | Patient, explains step-by-step | Learning and documentation |
| Organizer | Strategic planner, structured | Task planning and architecture |

Custom personas are defined in `Memory/custom_personas.json` (M5).

---

## LLM Backend Priority

The `llm_interface.py` loads backends in this order:

1. **Ollama** — if `http://localhost:11434` is reachable
2. **llama-cpp-python** — if a `.gguf` file exists in `AIEngine/LLaMA2-13B/`
3. **Stub** — always available as fallback

Override via `ARBITER_MODEL_PATH` in `.env`, or via `configs/config.toml` for the Engine.

---

## Visual Studio Extension Spec

### Package Registration (ArbiterPackage.cs)

```csharp
[PackageRegistration(UseManagedResourcesOnly = true, AllowsBackgroundLoading = true)]
[Guid("...")]
[ProvideMenuResource("Menus.ctmenu", 1)]
[ProvideToolWindow(typeof(ChatToolWindow))]
[ProvideOptionPage(typeof(ArbiterOptionsPage), "Arbiter", "General", 0, 0, true)]
public sealed class ArbiterPackage : AsyncPackage { ... }
```

### Command IDs

```csharp
public static class PackageIds
{
    public const int CmdAskArbiter     = 0x0100; // Ctrl+Shift+A
    public const int CmdExplain        = 0x0101; // Ctrl+Shift+E
    public const int CmdFix            = 0x0102; // Ctrl+Shift+F
    public const int CmdRefactor       = 0x0103; // Ctrl+Shift+R
    public const int CmdGenerateTests  = 0x0104; // Ctrl+Shift+T
    public const int CmdAddDocs        = 0x0105; // Ctrl+Shift+D
    public const int CmdReviewFile     = 0x0106; // Ctrl+Shift+V
    public const int CmdInsertCode     = 0x0107; // Ctrl+Shift+I
    public const int CmdOpenChatPanel  = 0x0108; // Ctrl+Alt+A
}
```

### Backend Auto-Detection

On startup, `ArbiterPackage` checks ports 8000 and 8001 and connects to whichever is live. The active URL is stored in `ArbiterSettings.BackendUrl` (default: `http://127.0.0.1:8000`).

---

## Self-Build Loop Spec

### Roadmap Task Selection

The `SelfBuildController` selects the next task using this priority:
1. Tasks with `"status": "in_progress"` in `roadmap.json`
2. First task with `"status": "pending"` in the current milestone
3. First task with `"status": "pending"` across all milestones

### Commit Message Format

```
[arbiter-self-build] M7-3: Task planning — AI generates step-by-step implementation plan

- Created AIEngine/ArbiterEngine/core/task_planner.py
- Added /self-build/plan endpoint to server.py
- Added unit tests in tests/test_task_planner.py

Roadmap: M7-3 → done
Self-build mode: SemiAuto
```

### Safety Rules (FullAuto Mode)

Files that are **never** modified by self-build in FullAuto mode:
- `AIEngine/ArbiterEngine/configs/config.toml`
- `HostApp/Config/settings.json`
- `.env`
- `*.vsixmanifest`
- `roadmap.json` (read-only in FullAuto, only updated in SemiAuto with approval)

---

## Memory Layout

```
Memory/
├── ConversationLogs/
│   └── <project_name>.db          # SQLite — messages table (role, content, timestamp)
├── snippets.json                   # [{id, name, language, content, created_at}]
├── notes.json                      # [{project, content, created_at}]
├── custom_personas.json            # [{name, system_prompt}] — M5
├── session_memory.json             # {key: value, ...} — M5
└── Archive/
    ├── archive.json                # [{id, title, summary, content, tags, source_path}]
    └── library_config.json         # {paths: ["/path/to/library", ...]}
```

---

## Development Environment

| Task | Command |
|------|---------|
| Run Python bridge | `python AIEngine/PythonBridge/fastapi_bridge.py` |
| Run Arbiter Engine | `python AIEngine/ArbiterEngine/server.py` |
| Build WPF app | `cd HostApp && dotnet build` |
| Run WPF app | `cd HostApp && dotnet run` |
| Install Python deps | `pip install -r AIEngine/PythonBridge/requirements.txt` |
| Install Engine modules | `python AIEngine/ArbiterEngine/setup_modules.py` |
| Build VSIX | Open `VisualStudioExtension/` in VS 2022, Build Solution |
