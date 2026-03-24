# Architecture

Arbiter is a three-pillar, fully local, self-improving AI development platform.
This document describes the system architecture, component boundaries, data flow,
and communication protocols.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          ARBITER PLATFORM                                    │
│                                                                               │
│  ┌───────────────────┐   ┌──────────────────────┐   ┌───────────────────┐   │
│  │   PILLAR 1        │   │   PILLAR 2            │   │   PILLAR 3        │   │
│  │   CHAT ENGINE     │   │   VS INTEGRATION      │   │   SELF-ITERATION  │   │
│  │                   │   │                        │   │                   │   │
│  │  Multi-turn chat  │   │  Native VSIX extension │   │  Reads roadmap    │   │
│  │  RAG + Archive    │   │  Inline completions    │   │  Plans & codes    │   │
│  │  Voice I/O        │   │  9 VS commands         │   │  Tests & commits  │   │
│  │  Personas         │   │  Build error AI fixes  │   │  4 autonomy modes │   │
│  └────────┬──────────┘   └──────────┬─────────────┘   └────────┬──────────┘   │
│           │                         │                           │              │
│           └─────────────────────────┼───────────────────────────┘              │
│                                     │                                           │
│                         ┌───────────▼───────────┐                              │
│                         │   ARBITER ENGINE       │                              │
│                         │   FastAPI  port 8001   │                              │
│                         │   200+ tools           │                              │
│                         │   12 LLM backends      │                              │
│                         └───────────┬────────────┘                              │
│                                     │                                           │
│                         ┌───────────▼───────────┐                              │
│                         │  PYTHON BRIDGE         │                              │
│                         │  FastAPI  port 8000    │                              │
│                         │  Lightweight mode      │                              │
│                         └───────────────────────┘                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Component Map

### HostApp — C# WPF Windows Application (`.NET 8`)

| File | Role |
|------|------|
| `LauncherWindow.xaml.cs` | Start-up mode picker (ArbiterAI or Engine), starts server subprocess |
| `IdeWindow.xaml.cs` | Full-screen Monaco IDE via WebView2; native menu/toolbar/statusbar; tray icon |
| `MainWindow.xaml.cs` | Project list manager; basic chat; server health check |
| `ProjectWindow.xaml.cs` | Per-project: chat, file tree, git panel |
| `WorkspaceWindow.xaml.cs` | Drag-and-drop workspace manager |
| `App.xaml.cs` | Application lifecycle; shutdown prompt (keep servers/shut down) |
| `AppConfig.cs` | Shared runtime state: mode, API URL, server processes |
| `BuildInterface/BuildManager.cs` | dotnet / npm / cargo / python build orchestrator |
| `GitInterface/GitManager.cs` | LibGit2Sharp git operations |
| `VoiceInterface/VoiceManager.cs` | TTS (System.Speech) + STT (Whisper) |
| `Updater.cs` | GitHub Releases auto-update check |

### AIEngine/PythonBridge — FastAPI (port 8000)

Lightweight bridge server. Handles chat, code actions, build/run/test, Monaco IDE GUI.
Recommended for first-run and environments without heavy GPU resources.

| File | Role |
|------|------|
| `fastapi_bridge.py` | Main FastAPI server (2000+ lines) |
| `llm_interface.py` | Hardware-aware LLM loading (llama.cpp, Ollama, OpenAI) |
| `persona_manager.py` | Persona system (load, set, list, create custom) |
| `archive_manager.py` | Archive/codex indexing and BM25 search |
| `library_manager.py` | Library path management |
| `model_downloader.py` | HuggingFace Hub auto-download with VRAM detection |
| `VoiceManager.py` | TTS via pyttsx3 |
| `static/index.html` | ChatGPT-style standalone web UI |
| `gui/` | Monaco IDE web UI (40+ panels) |

### AIEngine/ArbiterEngine — FastAPI (port 8001)

Full agentic engine. Implements the same REST API as PythonBridge plus
200+ additional tools, self-build loop, 12 LLM backends, plugin system.

| File | Role |
|------|------|
| `server.py` | Main FastAPI server (7000+ lines) |
| `core/agent.py` | Basic agent orchestrator |
| `core/agentic_agent.py` | Full agentic loop (plan → identify → code → test → commit) |
| `core/self_build.py` | SelfBuildController — roadmap-driven autonomous self-build |
| `core/logger.py` | Logging setup; per-system logs; workspace JSONL logs |
| `core/task_runner.py` | Background task queue |
| `core/module_loader.py` | Dynamic module loading |
| `core/plugin_loader.py` | Plugin marketplace integration |
| `core/permission.py` | Permission system (Manual/Assist/SemiAuto/FullAuto) |
| `core/tool_registry.py` | Tool registration and dispatch |
| `llm/factory.py` | LLM factory — detects and initialises the configured backend |
| `llm/backends/` | 12 LLM backend adapters |
| `modules/issues/` | Local git-backed issues tracker |
| `configs/config.toml` | Runtime configuration |

### VisualStudioExtension — VSIX (Visual Studio 2022)

| File | Role |
|------|------|
| `ArbiterPackage.cs` | VS Package entry point; backend auto-detect |
| `ChatToolWindow.cs` | Dockable Arbiter chat panel (WebView2) |
| `InlineSuggestionProvider.cs` | Roslyn inline AI completions (`// Arbiter:` trigger) |
| `ArbiterCommands.cs` | 9 VS commands with keyboard shortcuts |
| `EventHandlers.cs` | Document / build / solution event handlers |
| `ArbiterSettings.cs` | Tools → Options → Arbiter AI settings page |
| `SelfBuildToolWindow.cs` | Self-build status + controls in VS |

---

## Data Flow

### Chat Request Flow

```
User types message
       │
       ▼
WPF / Monaco / VSIX chat panel
       │  HTTP POST /chat or /assistant/chat
       ▼
FastAPI server (8000 or 8001)
       │  context injection (file, selection, project)
       ▼
Persona system → system prompt assembly
       │
       ▼
LLM backend (llama.cpp / Ollama / OpenAI / ...)
       │  streaming tokens (SSE or WebSocket)
       ▼
Chat panel renders response
       │  optionally: apply diff, TTS, commit
       ▼
SQLite conversation history saved
```

### Self-Build Flow

```
/self-build/start (mode: assist/semiauto/fullauto)
       │
       ▼
SelfBuildController reads roadmap.json
       │  picks next pending task
       ▼
AI generates step-by-step plan
       │
       ▼
AI identifies files to create/modify
       │
       ▼
AI writes unified diff patches
       │  syntax validation (Python AST / dotnet build)
       ▼
[Assist/SemiAuto] → Approval prompt → user approves/rejects
[FullAuto]        → auto-apply
       │
       ▼
Apply patches to filesystem
       │  run tests
       ▼
git commit with [arbiter-self-build] tag
       │
       ▼
roadmap.json task marked done
       │
       ▼
Loop repeats with next pending task
```

---

## Communication Protocols

| Protocol | Usage |
|----------|-------|
| HTTP REST | All standard API calls (chat, code actions, build, git, etc.) |
| Server-Sent Events (SSE) | Streaming chat responses (`/chat/stream`) |
| WebSocket | Real-time build output (`/ws/run`), PTY terminal (`/ws/pty`), chat (`/ws/chat`) |
| postMessage (WebView2) | WPF ↔ Monaco JS bridge for native file pickers, notifications |
| Named pipes / stdout | WPF ↔ Python subprocess communication |

---

## Port Assignments

| Service | Port | Protocol |
|---------|------|----------|
| PythonBridge | 8000 | HTTP / WS |
| ArbiterEngine | 8001 | HTTP / WS |
| Monaco IDE (via Bridge) | 8000 | HTTP |
| Monaco IDE (via Engine) | 8001 | HTTP |

---

## Storage Layout

```
<repo_root>/
├── Memory/
│   ├── ConversationLogs/       # Per-project SQLite chat history
│   ├── snippets.json           # Saved code snippets
│   ├── notes.json              # Per-project notes
│   └── Archive/archive.json   # Knowledge codex (BM25-indexed)
│
├── Projects/                   # User project workspaces
│   └── <project_name>/
│       └── .arbiter/
│           ├── logs/workspace.jsonl   # Structured JSONL log (per workspace)
│           ├── self_build_log.json    # All diffs from self-build sessions
│           └── issues/                # Local git-backed issue tracker
│
├── logs/                       # Aggregated per-system rotating log files
│   ├── arbiter_engine/         # ArbiterEngine (server.py)
│   ├── python_bridge/          # PythonBridge (fastapi_bridge.py)
│   ├── host_app/               # WPF HostApp events
│   ├── vs_extension/           # VS extension events
│   └── self_build/             # Self-build loop activity
│
└── HostApp/Config/settings.json   # WPF app configuration
```

---

## Technology Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Windows UI | C# WPF | .NET 8 |
| VS Extension | C# VSIX | VS 2022 SDK |
| AI Backend | Python FastAPI | 0.115+ |
| LLM Inference | llama-cpp-python (GGUF) | latest |
| LLM Alternatives | Ollama, OpenAI, Anthropic, Gemini, LM Studio, LocalAI, OpenWebUI, Tabby | – |
| TTS | pyttsx3 / System.Speech | – |
| STT | Whisper / Windows Speech | – |
| Editor (Web) | Monaco Editor | – |
| Terminal (Web) | xterm.js | – |
| Git (C#) | LibGit2Sharp | – |
| Git (Python) | GitPython | – |
| Vector Search | BM25 (Archive) / ChromaDB | – |
| Memory | SQLite + JSON | – |
| Container | Docker + docker-compose | – |
| Installer | Inno Setup 6 | – |
