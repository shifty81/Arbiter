# ArbiterAI

**Arbiter** is a self-hosted, fully offline AI-powered development platform. It is not just a chatbot — it is a controllable, self-iterating AI agent built around three tightly integrated pillars:

```
┌──────────────────┬───────────────────────┬──────────────────────┐
│   PILLAR 1       │    PILLAR 2            │    PILLAR 3          │
│   CHAT ENGINE    │    VISUAL STUDIO       │    SELF-ITERATION    │
│                  │    INTEGRATION         │                      │
│ Context-aware    │ Native VSIX extension  │ Reads own roadmap    │
│ multi-turn chat  │ Side panel in VS 2022  │ Plans & writes code  │
│ with full SDLC   │ Inline AI suggestions  │ Tests & commits      │
│ awareness        │ Tool windows           │ Reports progress     │
└──────────────────┴───────────────────────┴──────────────────────┘
```

Everything runs locally. No cloud required. Your code never leaves your machine.

---

## Core Development Loop

```
Idea → Chat with Arbiter → Plan Tasks → Generate Code → 
Edit in Monaco / Visual Studio → Build → Run → Test → 
AI Review → Fix → Commit → Repeat → Working Release
```

---

## Architecture

```
ArbiterAI/
├── Arbiter.sln                            # Visual Studio solution
│
├── HostApp/                               # C# WPF Windows application (.NET 8)
│   ├── App.xaml(.cs)                      # Startup — shows LauncherWindow
│   ├── AppConfig.cs                       # Static: mode, API URL, engine process
│   ├── LauncherWindow.xaml(.cs)           # Mode picker: ArbiterAI | Arbiter Engine
│   ├── MainWindow.xaml(.cs)              # Project list and management
│   ├── ProjectWindow.xaml(.cs)           # Per-project: chat, file tree, git
│   ├── IdeWindow.xaml(.cs)               # Monaco IDE embedded via WebView2
│   ├── WorkspaceWindow.xaml(.cs)         # Workspace drag-and-drop manager
│   ├── PdfViewerWindow.xaml(.cs)         # Read-only PDF viewer (WebView2)
│   ├── BuildInterface/BuildManager.cs    # dotnet / npm / cargo / python build runner
│   ├── GitInterface/GitManager.cs        # LibGit2Sharp integration
│   ├── VoiceInterface/                   # TTS (System.Speech) + STT (Whisper)
│   ├── Utilities/                        # DarkTitleBar, PythonHelper, InputDialog
│   ├── Themes/DarkTheme.xaml             # VS Code-inspired dark palette
│   └── Config/settings.json             # App configuration
│
├── VisualStudioExtension/                 # VSIX for Visual Studio 2022 (Pillar 2 — M6)
│   ├── ArbiterVSIX.csproj
│   ├── ArbiterPackage.cs                 # VS Package entry point
│   ├── ChatToolWindow.cs                 # Dockable Arbiter chat panel
│   ├── InlineSuggestionProvider.cs       # Inline AI completions
│   ├── ArbiterCommands.cs                # 9 VS commands + keyboard shortcuts
│   └── source.extension.vsixmanifest
│
├── AIEngine/
│   ├── PythonBridge/                      # Primary backend (port 8000)
│   │   ├── fastapi_bridge.py             # FastAPI server
│   │   ├── llm_interface.py              # Hardware-aware LLM loading
│   │   ├── persona_manager.py            # Persona system
│   │   ├── archive_manager.py            # Archive/codex indexing
│   │   ├── library_manager.py            # Library path management
│   │   ├── model_downloader.py           # HuggingFace Hub auto-download
│   │   ├── static/                       # Chat web UI
│   │   └── gui/                          # Monaco IDE web UI
│   │
│   └── ArbiterEngine/                     # Full agentic backend (port 8001, optional)
│       ├── server.py                      # FastAPI (same API contract as bridge)
│       ├── core/                          # agent, agentic_agent, self_build, task_runner
│       ├── llm/                           # factory + 12 backends
│       └── configs/config.toml           # Runtime configuration
│
├── Memory/
│   ├── ConversationLogs/                  # Per-project SQLite chat history
│   ├── snippets.json                      # Saved code snippets
│   ├── notes.json                         # Per-project notes
│   └── Archive/archive.json              # Archive codex
│
├── Projects/                              # User project workspaces
├── roadmap.json                           # Master project roadmap (M0–M8)
├── Repo Directive.md                      # Project direction and architecture guide
└── Specs.md                               # Technical specifications
```

---

## Modes

| Mode | Port | Description |
|---|---|---|
| **ArbiterAI** | 8000 | Lightweight bridge — chat, code actions, build/run/test, Monaco IDE |
| **Arbiter Engine** | 8001 | Full agentic engine — 200+ tools, 12 LLM backends, self-build loop |

The **Launcher** lets you choose at startup. Both modes serve the same API contract so the WPF client, Monaco IDE, and Visual Studio extension work identically with either.

---

## Feature Status

### Pillar 1 — Chat Engine

| Feature | Status | Milestone |
|---|---|---|
| ChatGPT-style web chat UI | ✅ Done | M0 |
| Voice output (TTS) | ✅ Done | M0 |
| Voice input (STT — Whisper + Windows Speech) | ✅ Done | M0 |
| Persona system (Arbiter / Coder / Teacher / Organizer) | ✅ Done | M0 |
| Per-project SQLite conversation history | ✅ Done | M0 |
| Streaming responses (WebSocket) | ✅ Done | M1 |
| AI code actions (complete, explain, fix, refactor, docstring, tests) | ✅ Done | M1 |
| Context-aware chat with file context injection | ✅ Done | M1 |
| Markdown rendering with syntax-highlighted code blocks | ✅ Done | M1 |
| Inline diff preview before applying AI changes | 📋 M5 | M5 |
| File attachment in chat | 📋 M5 | M5 |
| Slash commands (/build, /run, /test, /commit, /task, /agent) | 📋 M5 | M5 |
| RAG search over Archive codex | 📋 M5 | M5 |
| Chat export (Markdown / PDF) | 📋 M5 | M5 |
| Custom personas | 📋 M5 | M5 |
| Multi-agent orchestration | 📋 M5 | M5 |

### Pillar 2 — Visual Studio Integration

| Feature | Status | Milestone |
|---|---|---|
| VSIX project scaffold and package | 📋 M6 | M6 |
| Arbiter chat panel (dockable tool window) | 📋 M6 | M6 |
| Inline AI completions (// Arbiter: trigger) | 📋 M6 | M6 |
| Ask / Explain / Fix / Refactor / Tests / Docs commands | 📋 M6 | M6 |
| Build error → AI fix suggestions in Error List | 📋 M6 | M6 |
| Document and solution event context sync | 📋 M6 | M6 |
| Status bar + Output window integration | 📋 M6 | M6 |
| Tools → Options → Arbiter settings page | 📋 M6 | M6 |
| VS Marketplace packaging and publication | 📋 M8 | M8 |

### Pillar 3 — Self-Iteration

| Feature | Status | Milestone |
|---|---|---|
| Self-build infrastructure (loop, diff, apply) | ✅ Done | M2 |
| Four autonomy modes (Manual / Assist / SemiAuto / FullAuto) | 📋 M7 | M7 |
| Task planning: AI generates step-by-step implementation plan | 📋 M7 | M7 |
| Syntax validation before applying changes | 📋 M7 | M7 |
| Test execution after changes | 📋 M7 | M7 |
| Structured commit messages [arbiter-self-build] | 📋 M7 | M7 |
| Roadmap.json auto-update after task completion | 📋 M7 | M7 |
| Self-build panel in Monaco IDE | 📋 M7 | M7 |
| Self-build controls in VS extension | 📋 M7 | M7 |

### Platform Features

| Feature | Status | Milestone |
|---|---|---|
| WPF dark-theme Windows client | ✅ Done | M0 |
| Hardware-aware LLM loading (GGUF + Ollama + stub) | ✅ Done | M0 |
| Build / run / test loop (dotnet, npm, Python, Cargo, Make) | ✅ Done | M0 |
| Git integration (commit, push, pull, branch, log) | ✅ Done | M0 |
| Automated model download (HuggingFace Hub) | ✅ Done | M0 |
| Monaco IDE web UI (40+ panels) | ✅ Done | M1 |
| File CRUD API | ✅ Done | M1 |
| Arbiter Engine — 12 LLM backends | ✅ Done | M2 |
| Arbiter Engine — module / plugin system | ✅ Done | M2 |
| Archive & Library codex | 🔄 M3 | M3 |
| WPF IDE full native client | 📋 M4 | M4 |
| NSIS installer | 📋 M8 | M8 |

---

## Quick Start

### Prerequisites

- Windows 10/11
- [.NET 8 SDK](https://dotnet.microsoft.com/download)
- Python 3.10+
- [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/) (pre-installed on Win 11)
- Visual Studio 2022 (for WPF app or VSIX extension development)

### 1 — One-click setup

```bash
python setup_arbiter.py
```

This installs Python dependencies, detects your GPU, and downloads the best-fit model.

### 2 — Start the Python bridge

```bash
python AIEngine/PythonBridge/fastapi_bridge.py
# Bridge: http://127.0.0.1:8000
# Monaco IDE: http://127.0.0.1:8000/gui/
```

### 3 — Build and run the WPF app

```bash
cd HostApp && dotnet build && dotnet run
# OR open Arbiter.sln in Visual Studio 2022 and press F5
```

The Launcher will appear — choose **ArbiterAI** for the standard bridge or **Arbiter Engine** for the full agentic mode.

### 4 — (Optional) Install Ollama for best AI quality

```bash
# https://ollama.com
ollama pull llama3
```

### 5 — (Optional) Install Arbiter Engine modules

```bash
python AIEngine/ArbiterEngine/setup_modules.py
```

---

## Monaco IDE

The built-in Monaco IDE (available at `/gui/`) provides a full VS Code-like web editor with:

- **Explorer** — file tree with create, rename, delete
- **Monaco Editor** — syntax highlighting (100+ languages), IntelliSense, diff view, multi-tab
- **AI Chat panel** — context-aware Arbiter chat while editing code
- **Terminal** — xterm.js PTY streamed via WebSocket
- **Git panel** — staged/unstaged/untracked, commit, log, diff
- **Build panel** — real-time streaming output
- **Archive sidebar** — search and browse the knowledge codex
- **40+ tool panels** — Scaffold, Brainstorm, Refactor, DocGen, Deploy, Docker, DB, Vault, and more

---

## API Reference

### Chat

```
POST /chat                        Send a message, get a response + TTS
POST /assistant/chat              IDE-aware chat with file context
POST /assistant/chat/agentic      Triggers AgenticChatEngine
GET  /history/{project}           Retrieve conversation history
GET  /personas                    List available personas
POST /persona/{project}           Set active persona
```

### Files & Code Actions

```
GET  /files                       List files in project directory
POST /files/read                  Read file content
POST /files/write                 Write file content
POST /files/delete                Delete file
POST /files/rename                Rename file
POST /ai/complete                 AI code completion
POST /ai/action                   AI code action (explain/fix/refactor/docstring/tests)
POST /ai/propose                  AI propose change with diff preview
```

### Build, Run, Test

```
POST /build                       Build project (auto-detects command)
POST /run                         Run project entry point
POST /test                        Run project test suite
WS   /ws/run                      Streaming build output
WS   /ws/pty                      PTY terminal
```

### Git

```
GET  /git/status                  Working tree status
POST /git/stage                   Stage files
POST /git/commit                  Commit with message
GET  /git/log                     Commit history
GET  /git/diff                    File or commit diff
POST /git/clone                   Clone remote repository
```

### Archive & Library

```
GET  /archive                     Full archive listing
GET  /archive/search?q=           Keyword search
POST /archive/rebuild             Re-index all library paths
GET  /archive/export              Export as Markdown codex
GET  /library                     List library paths
POST /library                     Add library path
DELETE /library/{id}              Remove library path
```

---

## Roadmap

See [`roadmap.json`](roadmap.json) for the full task-level breakdown.

| Milestone | Description | Status |
|---|---|---|
| M0 — Foundation | WPF shell, chat, voice, personas, git, build | ✅ Done |
| M1 — IDE Integration | Monaco IDE, WebView2, File CRUD, AI code actions | ✅ Done |
| M2 — Arbiter Engine | 12 LLM backends, agentic loop, module/plugin system | 🔄 In Progress |
| M3 — Archive & Library | Knowledge codex, background indexer, context injection | 🔄 In Progress |
| M4 — WPF IDE | Full native client, status bar, menu bar, shortcuts | 📋 Planned |
| M5 — Advanced Chat | RAG, slash commands, inline diff, multi-agent, voice-in-IDE | 📋 Planned |
| **M6 — Visual Studio Integration** | **VSIX extension, chat panel, inline suggestions, 9 commands** | **📋 Planned** |
| **M7 — Self-Iteration** | **Autonomous self-build loop, 4 modes, roadmap-driven** | **📋 Planned** |
| M8 — Distribution | NSIS installer, auto-update, CLI, Docker, VS Marketplace | 📋 Planned |

---

## Configuration

**`HostApp/Config/settings.json`** — WPF app settings:
```json
{
  "default_voice": "British_Female",
  "tts_enabled": true,
  "arbiterEnginePath": "AIEngine/ArbiterEngine",
  "arbiterEnginePort": 8001,
  "git_author_name": "ArbiterUser",
  "git_author_email": "arbiter@local"
}
```

**`AIEngine/ArbiterEngine/configs/config.toml`** — Engine settings:
LLM backend selection, tool permissions, agent behaviour, self-build mode.

---

## Technology Stack

| Layer | Technology |
|---|---|
| Windows UI | C# WPF / .NET 8 |
| VS Extension | C# VSIX / Visual Studio 2022 SDK |
| AI Backend | Python FastAPI |
| LLM Inference | llama-cpp-python (GGUF) |
| LLM Alternatives | Ollama, OpenAI API, Anthropic, Gemini, LM Studio, LocalAI, OpenWebUI, Tabby |
| TTS | pyttsx3 / System.Speech |
| STT | Whisper / Windows Speech |
| Editor (Web) | Monaco Editor |
| Terminal (Web) | xterm.js |
| Git | LibGit2Sharp (C#) + GitPython (Python) |
| Vector Search | ChromaDB / FAISS (M5) |
| Memory | SQLite (conversations) + JSON (config, archive, snippets) |

---

## Contributing

This is an active solo project. Issues and PRs are welcome — check `roadmap.json` first to avoid duplicating in-progress work.

AI-generated commits from the self-build loop are tagged with `[arbiter-self-build]` in the commit message.

---

## License

MIT
