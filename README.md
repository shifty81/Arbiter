<div align="center">

```
 █████╗ ██████╗ ██████╗ ██╗████████╗███████╗██████╗
██╔══██╗██╔══██╗██╔══██╗██║╚══██╔══╝██╔════╝██╔══██╗
███████║██████╔╝██████╔╝██║   ██║   █████╗  ██████╔╝
██╔══██║██╔══██╗██╔══██╗██║   ██║   ██╔══╝  ██╔══██╗
██║  ██║██║  ██║██████╔╝██║   ██║   ███████╗██║  ██║
╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝
```

**Self-hosted · Fully Offline · AI-Powered Development Platform**

![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078d4?style=flat-square&logo=windows)
![.NET](https://img.shields.io/badge/.NET-8.0-512bd4?style=flat-square&logo=dotnet)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776ab?style=flat-square&logo=python)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)
![Version](https://img.shields.io/badge/version-1.1.0-blue?style=flat-square)
![Milestones](https://img.shields.io/badge/milestones-M0–M14%20✅%20complete-brightgreen?style=flat-square)
![Docs](https://img.shields.io/badge/docs-wiki-orange?style=flat-square)

</div>

---

## 🗺️ Roadmap

> Full task breakdown: [`roadmap.json`](roadmap.json) · Human-readable: [`ROADMAP.md`](ROADMAP.md) · Wiki: [`docs/wiki/ROADMAP.md`](docs/wiki/ROADMAP.md)

```
COMPLETED ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  M0 ✅ Foundation       M1 ✅ IDE Integration    M2 ✅ Arbiter Engine
  M3 ✅ Archive/Library  M4 ✅ WPF IDE            M5 ✅ Advanced Chat
  M6 ✅ VS Integration   M7 ✅ Self-Iteration     M8 ✅ Distribution
  M9 ✅ Productivity    M10 ✅ Enhanced Chat     M11 ✅ Advanced AI
 M12 ✅ Logging/Issues  M13 ✅ Reliability       M14 ✅ Code Quality

ACTIVE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Phase 1 🔄 Platform Consolidation   (per-system logs, docs wiki, shutdown prompt)

PLANNED ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Phase 2 🔜 Tooling Layer & AI       Phase 3 🔜 SteamServerAdmin ⬡
  Phase 4 🔜 Game Systems & PCG ⬡     Phase 5 🔜 Development Agent
  Phase 6 🔜 Integration & Testing    Phase 7 🔜 Deployment & Scaling

  ⬡ = standalone managed project (Novaforge / SteamServerAdmin)
```

---

## 🛠️ Tool Suite

Arbiter ships with dedicated AI-powered tools, each with its own icon inside the interface:

```
  💬 Chat Engine          🔮 AI Backends          🤖 Multi-Agent
  🏗️ Scaffold             ✏️  Refactor              📝 DocGen
  🧪 Test Runner          🔍 Code Quality          🔒 Security Audit
  🌿 Git Panel            🔨 Build & Run           🚀 Deploy Manager
  🐳 Docker IDE           📡 CI Integration        ⏰ Cron Scheduler
  📊 Analytics            📚 Knowledge Archive     🗃️ API Client
  🔌 Plugin Manager       💾 Cloud Sync            🖥️ Monaco IDE
  🗺️ Roadmap Viewer       📋 Issues Tracker        📜 Audit Log
```

---

## What is Arbiter?

**Arbiter** is not a chatbot wrapper. It is a complete, self-improving AI development platform that runs entirely on your machine — no cloud, no telemetry, no subscriptions. It is built around three tightly integrated pillars:

```
┌──────────────────────┬─────────────────────────┬──────────────────────────┐
│   PILLAR 1           │   PILLAR 2              │   PILLAR 3               │
│   CHAT ENGINE        │   VISUAL STUDIO         │   SELF-ITERATION         │
│                      │   INTEGRATION           │                          │
│  Context-aware       │  Native VSIX extension  │  Reads its own roadmap   │
│  multi-turn chat     │  Side panel in VS 2022  │  Plans & writes code     │
│  Full SDLC lifecycle │  Inline AI suggestions  │  Tests & commits         │
│  RAG + Archive codex │  9 VS commands          │  4 autonomy modes        │
│  Voice I/O           │  Build error AI fixes   │  Autonomous self-build   │
└──────────────────────┴─────────────────────────┴──────────────────────────┘
```

> **Everything runs locally. No cloud required. Your code never leaves your machine.**

---

## Managed Projects

Arbiter manages the following standalone projects as first-class AI-driven workspaces.
Each project lives in `Projects/` with its own `roadmap.json`, wiki documentation, and
is fully accessible from the Chat Engine, self-build loop, and Tooling Layer.

```
  🎮 Novaforge          — Game dev: Atlas Core+ECS · Mech suits · PCG
  🖥️ SteamServerAdmin   — Server admin: autonomous start/stop/update · role permissions · AI monitoring
```

| Project | Wiki | Project Roadmap |
|---------|------|----------------|
| [Novaforge](docs/wiki/NOVAFORGE.md) | Game development — Atlas Core+ECS, mech suit systems, AI-powered PCG | [`Projects/Novaforge/roadmap.json`](Projects/Novaforge/roadmap.json) |
| [SteamServerAdmin](docs/wiki/STEAM_SERVER_ADMIN.md) | Standalone autonomous Steam game server administration | [`Projects/SteamServerAdmin/roadmap.json`](Projects/SteamServerAdmin/roadmap.json) |

---

## What This Repository Contains

| Component | Location | Description |
|-----------|----------|-------------|
| 🖥️ **WPF Desktop App** | `HostApp/` | C# WPF Windows client — launcher, project manager, IDE window, git panel, voice |
| 🤖 **AI Backend (Primary)** | `AIEngine/PythonBridge/` | FastAPI server on port 8000 — chat, code actions, build/run/test, Monaco IDE |
| 🔮 **Arbiter Engine** | `AIEngine/ArbiterEngine/` | Full agentic FastAPI server on port 8001 — 12 LLM backends, self-build loop, 200+ tools |
| 🔌 **Visual Studio Extension** | `VisualStudioExtension/` | VSIX for VS 2022 — chat panel, inline completions, 9 AI commands, build error fixes |
| 🌐 **Monaco IDE (Web UI)** | `AIEngine/PythonBridge/gui/` | Full VS Code-like IDE in the browser — 40+ panels, file tree, terminal, AI chat |
| 💬 **Chat Web UI** | `AIEngine/PythonBridge/static/` | Standalone ChatGPT-style chat interface |
| 📚 **Knowledge Archive** | `Memory/Archive/` | Indexed codex of library knowledge, code snippets, documentation |
| 🗺️ **Project Roadmap** | `roadmap.json` | Machine-readable roadmap driving the self-build loop |
| 🐳 **Docker** | `Dockerfile`, `docker-compose.yml` | One-command backend deployment |
| 📦 **Installer** | `Installer/` | Inno Setup 6 installer script for Windows |

---

## Core Development Loop

```
Idea ──► Chat with Arbiter ──► Plan Tasks ──► Generate Code
                                                    │
Working Release ◄── Commit ◄── Fix ◄── AI Review ◄──┘
                                         │
                                  Build ─► Run ─► Test
```

The self-build loop closes the outermost circle: Arbiter reads `roadmap.json`, picks the next task, writes code, tests it, and commits — then repeats.

---

## Architecture

```
ArbiterAI/
├── Arbiter.sln                            # Visual Studio solution
│
├── HostApp/                               # C# WPF Windows app (.NET 8)
│   ├── LauncherWindow.xaml(.cs)           # Startup mode picker
│   ├── MainWindow.xaml(.cs)              # Project list & management
│   ├── ProjectWindow.xaml(.cs)           # Per-project: chat, file tree, git
│   ├── IdeWindow.xaml(.cs)               # Monaco IDE via WebView2 (full-screen)
│   ├── WorkspaceWindow.xaml(.cs)         # Drag-and-drop workspace manager
│   ├── BuildInterface/BuildManager.cs    # dotnet / npm / cargo / python build
│   ├── GitInterface/GitManager.cs        # LibGit2Sharp git operations
│   ├── VoiceInterface/                   # TTS (System.Speech) + STT (Whisper)
│   ├── Themes/DarkTheme.xaml             # VS Code-inspired dark palette
│   ├── Updater.cs                        # GitHub Releases auto-update
│   └── Config/settings.json             # App configuration
│
├── VisualStudioExtension/ArbiterVSIX/    # VSIX for Visual Studio 2022
│   ├── ArbiterPackage.cs                 # VS Package entry point + backend auto-detect
│   ├── ChatToolWindow.cs                 # Dockable Arbiter chat panel (WebView2)
│   ├── InlineSuggestionProvider.cs       # Roslyn inline AI completions
│   ├── ArbiterCommands.cs                # 9 VS commands with keyboard shortcuts
│   ├── EventHandlers.cs                  # Document / build / solution events
│   ├── ArbiterSettings.cs                # Tools → Options → Arbiter AI page
│   └── SelfBuildToolWindow.cs            # Self-build status + controls in VS
│
├── AIEngine/
│   ├── PythonBridge/                     # Primary backend (port 8000)
│   │   ├── fastapi_bridge.py             # FastAPI server (2000+ lines)
│   │   ├── llm_interface.py              # Hardware-aware LLM loading
│   │   ├── persona_manager.py            # Persona system
│   │   ├── archive_manager.py            # Archive/codex indexing
│   │   ├── library_manager.py            # Library path management
│   │   ├── model_downloader.py           # HuggingFace Hub auto-download
│   │   ├── static/index.html             # Chat web UI
│   │   └── gui/                          # Monaco IDE web UI (40+ panels)
│   │
│   ├── ArbiterEngine/                    # Full agentic backend (port 8001)
│   │   ├── server.py                     # FastAPI (same API contract, 4800+ lines)
│   │   ├── core/                         # agent, agentic_agent, self_build, task_runner
│   │   ├── llm/                          # factory + 12 LLM backends
│   │   └── configs/config.toml           # Runtime configuration
│   │
│   └── arbiter_cli.py                    # CLI: arbiter build/chat/archive/self-build
│
├── Memory/
│   ├── ConversationLogs/                 # Per-project SQLite chat history
│   ├── snippets.json                     # Saved code snippets
│   ├── notes.json                        # Per-project notes
│   └── Archive/archive.json             # Knowledge codex
│
├── Projects/                             # User project workspaces
├── Installer/arbiter_setup.iss           # Inno Setup 6 installer script
├── Dockerfile + docker-compose.yml       # Docker deployment
├── roadmap.json                          # Master project roadmap (M0–M11)
├── Repo Directive.md                     # Architecture & direction guide
└── Specs.md                              # Technical specifications
```

---

## Two Modes, Same API

| Mode | Port | Start Command | Description |
|------|------|---------------|-------------|
| **ArbiterAI** | 8000 | `python AIEngine/PythonBridge/fastapi_bridge.py` | Lightweight bridge — chat, code actions, build/run/test, Monaco IDE |
| **Arbiter Engine** | 8001 | `python AIEngine/ArbiterEngine/server.py` | Full agentic engine — 12 LLM backends, 200+ tools, self-build loop |

Both modes implement the same REST API contract. The WPF app, Monaco IDE, and VS extension work identically with either. The **Launcher** lets you choose on startup.

---

## Quick Start

### Prerequisites

- **Windows 10 / 11**
- [**.NET 8 SDK**](https://dotnet.microsoft.com/download)
- **Python 3.10+**
- [**Microsoft Edge WebView2 Runtime**](https://developer.microsoft.com/en-us/microsoft-edge/webview2/) _(pre-installed on Windows 11)_

### 1 — One-click setup

```bash
python setup_arbiter.py
```

Installs Python dependencies, detects your GPU, and downloads the best-fit model automatically.

### 2 — Start the AI backend

```bash
# Lightweight mode (recommended first run)
python AIEngine/PythonBridge/fastapi_bridge.py
# Chat UI  →  http://127.0.0.1:8000/
# Monaco IDE  →  http://127.0.0.1:8000/gui/

# Full agentic mode (self-build, 12 LLM backends, 200+ tools)
python AIEngine/ArbiterEngine/server.py
# API  →  http://127.0.0.1:8001/
```

### 3 — Build and run the WPF app

```bash
cd HostApp && dotnet build && dotnet run
# OR: open Arbiter.sln in Visual Studio 2022 → F5
```

Choose **ArbiterAI** or **Arbiter Engine** in the Launcher.

### 4 — (Optional) Use with Ollama for best AI quality

```bash
# Install Ollama from https://ollama.com
ollama pull llama3
```

### 5 — (Optional) Docker deployment (backend only)

```bash
docker-compose up arbiter-engine
# API → http://localhost:8001
# With Ollama: docker-compose --profile ollama up
```

### 6 — (Optional) Install the Visual Studio Extension

Open `VisualStudioExtension/ArbiterVSIX/` in Visual Studio 2022 and press **F5** to install the VSIX in the experimental instance, or use the pre-built `.vsix` from [Releases](https://github.com/shifty81/Arbiter/releases).

---

## Feature Overview

### Pillar 1 — Chat Engine

| Feature | Status |
|---------|--------|
| ChatGPT-style web chat UI | ✅ Done |
| Streaming responses (WebSocket / SSE) | ✅ Done |
| Persona system (Arbiter / Coder / Teacher / Organizer + custom) | ✅ Done |
| Per-project SQLite conversation history | ✅ Done |
| Voice output TTS (pyttsx3 / System.Speech) | ✅ Done |
| Voice input STT (Whisper / Windows Speech) | ✅ Done |
| Context-aware chat — file path, selection, project auto-injected | ✅ Done |
| File attachment — drag file into chat for AI context | ✅ Done |
| Inline diff preview before AI applies file changes | ✅ Done |
| RAG over Archive codex (BM25 keyword + context injection) | ✅ Done |
| Slash commands (`/build`, `/run`, `/test`, `/commit`, `/task`, `/agent`, `/search`) | ✅ Done |
| Code block actions — Apply, Copy, Save Snippet, Diff | ✅ Done |
| Chat export (Markdown) | ✅ Done |
| Full-text search across all conversation history | ✅ Done |
| Multi-agent orchestration (spawn sub-agents per task) | ✅ Done |
| Mermaid diagram generation | ✅ Done |
| Dependency vulnerability scanning | ✅ Done |
| Session memory (persistent key-value store per project) | ✅ Done |
| AI brainstorm sessions (LLM-powered ideation) | ✅ Done |
| AI documentation generator (docstrings, README, inline comments) | ✅ Done |
| Chat session branching & bookmarks | 🔜 M10 |
| Conversation templates | 🔜 M10 |
| AI response rating & feedback | 🔜 M10 |
| Multi-modal input (image/screenshot context) | 🔜 M10 |

### Pillar 2 — Visual Studio Integration

| Feature | Status |
|---------|--------|
| VSIX package — AsyncPackage, backend auto-detect | ✅ Done |
| Dockable Arbiter chat panel (WebView2-hosted) | ✅ Done |
| Inline AI completions (Roslyn, `// Arbiter:` trigger) | ✅ Done |
| 9 VS commands with keyboard shortcuts | ✅ Done |
| Context injection — active file + selection with every request | ✅ Done |
| Document / solution / build event handlers | ✅ Done |
| AI fix suggestions in VS Error List | ✅ Done |
| Active LLM backend in VS status bar | ✅ Done |
| Dedicated "Arbiter AI" output pane | ✅ Done |
| Tools → Options → Arbiter AI settings page | ✅ Done |
| Self-build status panel in VS | ✅ Done |
| VS Marketplace CI/CD publishing | ✅ Done |

### Pillar 3 — Self-Iteration

| Feature | Status |
|---------|--------|
| SelfBuildController — roadmap-driven pipeline | ✅ Done |
| Four autonomy modes: Manual / Assist / SemiAuto / FullAuto | ✅ Done |
| Task planning — AI generates numbered step-by-step plan | ✅ Done |
| File identification — AI identifies files to create/modify | ✅ Done |
| Code generation — AI writes unified diff patches | ✅ Done |
| Syntax validation (Python AST + dotnet build dry-run) | ✅ Done |
| Test execution (pytest / dotnet test / npm test) | ✅ Done |
| Iteration loop — retry up to 3× on failure | ✅ Done |
| Structured commit messages `[arbiter-self-build]` | ✅ Done |
| Roadmap auto-update after task completion | ✅ Done |
| Self-build REST API (`/self-build/start|stop|status|approve|reject|log`) | ✅ Done |
| Self-build panel in Monaco IDE | ✅ Done |
| Self-build panel in VS extension | ✅ Done |
| Safety constraints — never modifies protected files in FullAuto | ✅ Done |
| Session log — all diffs stored in `.arbiter/self_build_log.json` | ✅ Done |
| VSIX self-build support | ✅ Done |

### Platform & Productivity

| Feature | Status |
|---------|--------|
| Monaco IDE web UI — 40+ tool panels | ✅ Done |
| Archive & Library knowledge codex with background indexing | ✅ Done |
| Scaffold system — generate module/plugin/test boilerplate | ✅ Done |
| Code refactoring — regex find-replace + symbol rename across project | ✅ Done |
| Docker integration — list containers, build/run images from IDE | ✅ Done |
| Persistent task queue — background shell command execution | ✅ Done |
| Built-in API client — HTTP request tester with collections | ✅ Done |
| Test runner — collect, parse, store reports | ✅ Done |
| CI integration — trigger CI runs, view history | ✅ Done |
| Cron scheduler — recurring task execution | ✅ Done |
| Deployment manager — named deploy configs with run history | ✅ Done |
| Cloud sync — AES-256-GCM encrypted backup (S3/B2/local) | ✅ Done |
| Auto-update — GitHub Releases API | ✅ Done |
| Plugin marketplace | ✅ Done |
| CLI (`arbiter build / chat / archive / self-build`) | ✅ Done |
| Inno Setup Windows installer | ✅ Done |
| Cross-platform evaluation (CROSSPLATFORM.md) | ✅ Done |

---

## Monaco IDE Panels

The built-in web IDE at `/gui/` provides a full VS Code-like experience. The activity bar gives
one-click access to the most-used panels; all remaining panels are reachable via the **⋮ More**
overflow menu, which is organised into the following groups:

| Group | Panels |
|-------|--------|
| **Navigation** _(activity bar)_ | Explorer, File Search, Source Control (Git), AI Backends, Code Tools, CI/CD, Monitoring, Analytics, Notes, Settings |
| **AI & Agents** | Multi-Agent, Self-Build Loop, Brainstorm, Web Search |
| **Code Tools** | Refactor, Code Quality, Test Runner, Dep Analyzer, Doc Generator, Snippets, Diff & Patch, Templates, Utilities |
| **Project** | Roadmap, Knowledge, Library & Archive |
| **DevOps** | Docker, Deploy, API Client, Database, Terminal |
| **Operations** | Health Dashboard, Task Queue, Audit Log, Event Bus, Cron |
| **Config & Security** | Env Vars, Vault, Webhooks, Rate Limits, Feature Flags, Notifications |
| **Runtime** | Model Downloads, Plugins |

---

## VS Commands (Keyboard Shortcuts)

| Command | Shortcut | Action |
|---------|----------|--------|
| Ask Arbiter About Selection | `Ctrl+Shift+A` | Send selected code to Arbiter chat |
| Explain This Code | `Ctrl+Shift+E` | AI explains selected code |
| Fix This Error | `Ctrl+Shift+F` | AI fixes selected error / code |
| Refactor With Arbiter | `Ctrl+Shift+R` | AI refactors selected code |
| Generate Unit Tests | `Ctrl+Shift+T` | AI generates tests for selection |
| Add Documentation | `Ctrl+Shift+D` | AI writes docstrings / XML docs |
| Review This File | `Ctrl+Shift+V` | AI code review of the whole file |
| Open Arbiter Chat Panel | `Ctrl+Alt+A` | Toggles the Arbiter chat tool window |

---

## API Overview

Both backends expose the same API contract so all clients work with either.

### Chat

```http
POST /chat                        # Standard chat message
POST /assistant/chat              # IDE-aware chat with file context
POST /assistant/chat/agentic      # Trigger agentic plan→edit→test loop
GET  /history/{project}           # Conversation history
POST /history/{project}/export    # Export as Markdown
GET  /history/search?q=           # Full-text search across all history
GET  /personas                    # List personas
POST /persona/{project}           # Set active persona
POST /persona/custom              # Create / update custom persona
```

### AI Code Actions

```http
POST /ai/action                   # explain / fix / refactor / docstring / tests
POST /ai/complete                 # Inline code completion
POST /ai/propose                  # Propose change — returns unified diff
POST /ai/review                   # Structured code review
POST /ai/diff                     # Apply instruction; return diff
POST /ai/diagram                  # Generate Mermaid diagram
POST /docgen/generate             # AI docstring / README / inline comment generation
```

### Scaffold & Refactor

```http
POST /scaffold/module             # Generate boilerplate module
POST /scaffold/plugin             # Generate plugin scaffold
POST /scaffold/tests              # Generate test file
GET  /templates                   # List available templates
POST /templates/apply             # Apply a template
POST /refactor/find-replace       # Regex find-replace across project files
POST /refactor/rename             # Whole-word symbol rename across project files
```

### Build, Run, Test

```http
POST /build                       # Build project (auto-detected command)
POST /run                         # Run project entry point
POST /test                        # Run test suite
POST /testrunner/run              # Run tests + store report
GET  /testrunner/reports          # Test run history
WS   /ws/run                      # Streaming build output
WS   /ws/pty                      # PTY terminal
```

### Git

```http
GET  /git/status                  # Working tree status
POST /git/stage                   # Stage files
POST /git/commit                  # Commit with message
GET  /git/log                     # Commit history
GET  /git/diff                    # File or commit diff
POST /git/clone                   # Clone remote repository
```

### Archive & Library

```http
GET  /archive                     # Full archive listing
GET  /archive/search?q=           # Keyword search
POST /archive/rebuild             # Re-index all library paths
GET  /archive/export              # Export codex as Markdown
GET  /library                     # List library paths
POST /library                     # Add library path
```

### DevOps

```http
GET  /docker/containers           # List Docker containers
POST /docker/build                # Build Docker image
POST /docker/run                  # Run Docker container
POST /ci/run                      # Trigger CI run
GET  /ci/runs                     # CI run history
POST /deploy/config               # Create deploy configuration
POST /deploy/run                  # Execute deployment
GET  /deploy/history              # Deployment run history
POST /queue/task                  # Enqueue background command
GET  /queue/stats                 # Task queue statistics
POST /cron/job                    # Register cron job
```

### Self-Build

```http
POST /self-build/start            # Start self-build loop (mode: assist/semiauto/fullauto)
POST /self-build/stop             # Stop the loop
GET  /self-build/status           # Current task, progress, loop state
POST /self-build/approve          # Approve pending change (Assist / SemiAuto)
POST /self-build/reject           # Reject pending change
GET  /self-build/log              # Full self-build session log
GET  /self-build/roadmap          # Current roadmap JSON
```

---

## Roadmap

The full task-level breakdown is in [`roadmap.json`](roadmap.json) (drives the self-build loop) and [`ROADMAP.md`](ROADMAP.md) (human-readable). Detailed documentation in [`docs/wiki/ROADMAP.md`](docs/wiki/ROADMAP.md).

| Milestone | Description | Status |
|-----------|-------------|--------|
| **M0** — Foundation | WPF shell, chat, voice, personas, git, build/run/test | ✅ Complete |
| **M1** — IDE Integration | Monaco IDE, WebView2, File CRUD, AI code actions, WebSocket streaming | ✅ Complete |
| **M2** — Arbiter Engine | 12 LLM backends, agentic loop, module/plugin system, self-build infra | ✅ Complete |
| **M3** — Archive & Library | Knowledge codex, background indexer, keyword search, context injection | ✅ Complete |
| **M4** — WPF IDE | Full native client, status bar, menu bar, keyboard shortcuts, multi-window | ✅ Complete |
| **M5** — Advanced Chat | RAG, slash commands, inline diff, multi-agent, voice-in-IDE, dependencies scan | ✅ Complete |
| **M6** — Visual Studio Integration | VSIX extension, chat panel, inline suggestions, 9 commands, settings, events | ✅ Complete |
| **M7** — Self-Iteration | Autonomous self-build loop, 4 autonomy modes, roadmap-driven | ✅ Complete |
| **M8** — Distribution | Inno Setup installer, auto-update, plugin marketplace, CLI, Docker, cloud sync | ✅ Complete |
| **M9** — Productivity & Integration | Scaffold, docgen, refactor engine, Docker IDE, task queue, API client, test runner, CI, cron, deploy | ✅ Complete |
| **M10** — Enhanced Chat & AI | Chat branching, templates, feedback, multi-modal input, smart context, bookmarks, real-time render | ✅ Complete |
| **M11** — Advanced AI Intelligence | Multi-model routing, agents marketplace, code gen from requirements, knowledge graph | ✅ Complete |
| **M12** — Logging & Issues Tracking | Workspace JSONL logging, crash capture, rotating log files, local git-backed issues tracker | ✅ Complete |
| **M13** — Reliability & Performance | asyncio fix, timeout middleware, health endpoint, LRU cache, WS chat, LLM failover | ✅ Complete |
| **M14** — Code Quality & Security | Lint, dep security audit, complexity, duplicate detection, coverage, profiling, review workflow | ✅ Complete |
| **Phase 1** — Platform Consolidation | Per-system logs, docs wiki, server shutdown prompt, enhanced banner | 🔄 Active |
| **Phase 2–7** — Full Vision | Tooling layer, server management, game systems (PCG/mech), dev agent, deployment | 🔜 Planned |

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

**`AIEngine/ArbiterEngine/configs/config.toml`** — Agentic engine settings:
LLM backend selection, tool permissions, agent behaviour, self-build mode, task concurrency.

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
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
| Vector Search | BM25 keyword search (Archive) / ChromaDB (M11) |
| Memory | SQLite (conversations) + JSON (config, archive, snippets) |
| Container | Docker + docker-compose |
| Installer | Inno Setup 6 |

---

## Documentation

Arbiter ships with a comprehensive wiki intended to mirror to the in-application Wiki panel
and the GitHub repository wiki pages.

| Guide | Description |
|-------|-------------|
| 📖 [Architecture](docs/wiki/ARCHITECTURE.md) | System architecture, component map, data flow |
| 🚀 [Getting Started](docs/wiki/GETTING_STARTED.md) | Installation, setup, first run |
| ⚙️ [Configuration](docs/wiki/CONFIGURATION.md) | All settings files explained |
| 🔌 [API Reference](docs/wiki/API_REFERENCE.md) | Full REST + WebSocket API (200+ endpoints) |
| 📋 [Logging](docs/wiki/LOGGING.md) | Logging architecture and per-system log locations |
| 🔄 [Self-Build Loop](docs/wiki/SELF_BUILD.md) | Autonomous self-iteration system |
| 🔵 [VS Extension](docs/wiki/VS_EXTENSION.md) | Visual Studio 2022 VSIX extension guide |
| 💬 [Chat Engine](docs/wiki/CHAT_ENGINE.md) | Chat features, personas, slash commands, voice I/O |
| 🖥️ [Monaco IDE](docs/wiki/MONACO_IDE.md) | Built-in web IDE panels and features |
| 🗺️ [Roadmap](docs/wiki/ROADMAP.md) | Phase-by-phase project roadmap |
| 📜 [Changelog](docs/wiki/CHANGELOG.md) | Release history and notable changes |
| 🤝 [Contributing](docs/wiki/CONTRIBUTING.md) | Code conventions, PR process |
| 🔧 [Troubleshooting](docs/wiki/TROUBLESHOOTING.md) | Common problems and fixes |

---



This is an active solo project. Issues and PRs are welcome — check [`roadmap.json`](roadmap.json) first to avoid duplicating in-progress work.

AI-generated commits from the self-build loop are tagged with `[arbiter-self-build]` in the commit message so they are distinguishable from human commits.

---

## License

[MIT](LICENSE) © 2026 shifty81
