# Arbiter — Master Design Bible

> **Version 1.0** · Last updated automatically by Arbiter self-build loop
> This document is the single authoritative source of truth for the Arbiter platform's full system architecture, feature specifications, and all integration points.

---

## Table of Contents

1. [Vision & Goals](#1-vision--goals)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Component Specifications](#3-component-specifications)
   - 3.1 [WPF HostApp](#31-wpf-hostapp)
   - 3.2 [ArbiterEngine (port 8001)](#32-arbiterengine-port-8001)
   - 3.3 [PythonBridge (port 8000)](#33-pythonbridge-port-8000)
   - 3.4 [Visual Studio VSIX Extension](#34-visual-studio-vsix-extension)
   - 3.5 [SteamServerAdmin](#35-steamserveradmin)
4. [Feature Specifications](#4-feature-specifications)
   - 4.1 [Chat Engine](#41-chat-engine)
   - 4.2 [Self-Build Loop](#42-self-build-loop)
   - 4.3 [Archive & Library (RAG)](#43-archive--library-rag)
   - 4.4 [Code Analysis Suite](#44-code-analysis-suite)
   - 4.5 [Workspace & Projects](#45-workspace--projects)
   - 4.6 [Knowledge Graph](#46-knowledge-graph)
   - 4.7 [Issues Tracker](#47-issues-tracker)
   - 4.8 [Wiki Panel](#48-wiki-panel)
   - 4.9 [Changelog Automation](#49-changelog-automation)
5. [Integration Points](#5-integration-points)
   - 5.1 [WPF ↔ ArbiterEngine](#51-wpf--arbiterengine)
   - 5.2 [VSIX ↔ ArbiterEngine](#52-vsix--arbiterengine)
   - 5.3 [ArbiterEngine ↔ SteamServerAdmin](#53-arbiterengine--steamserveradmin)
   - 5.4 [ArbiterEngine ↔ Novaforge](#54-arbiterengine--novaforge)
   - 5.5 [Self-Build ↔ All Components](#55-self-build--all-components)
6. [Data Flow Diagrams](#6-data-flow-diagrams)
7. [REST & WebSocket API Contract](#7-rest--websocket-api-contract)
8. [LLM Backend Configuration](#8-llm-backend-configuration)
9. [Security & Permissions](#9-security--permissions)
10. [Deployment Targets](#10-deployment-targets)

---

## 1. Vision & Goals

Arbiter is a **three-pillar, fully local, self-improving AI development platform** built for professional developers who need a production-grade AI assistant that:

| Goal | Description |
|------|-------------|
| **Fully offline** | All AI inference runs locally via Ollama or other local backends. No cloud dependency. |
| **Self-iterating** | Arbiter reads its own roadmap and autonomously writes, tests, and commits code improvements. |
| **IDE-native** | Tight integration with Visual Studio 2022 via a full VSIX extension. |
| **Multi-project** | Manages multiple projects (Novaforge, SteamServerAdmin, etc.) as first-class workspaces. |
| **Production-ready** | Rotating logs, health endpoints, crash capture, budget tracking, metrics, failover LLM. |

---

## 2. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                              ARBITER PLATFORM                                    │
│                                                                                  │
│  ┌────────────────┐   ┌──────────────────────┐   ┌───────────────────────────┐  │
│  │  PILLAR 1      │   │  PILLAR 2             │   │  PILLAR 3                 │  │
│  │  CHAT ENGINE   │   │  VS INTEGRATION       │   │  SELF-ITERATION           │  │
│  │                │   │                       │   │                           │  │
│  │ Multi-turn     │   │ Native VSIX extension │   │ Reads roadmap.json        │  │
│  │ RAG + Archive  │   │ Inline completions    │   │ Plans tasks               │  │
│  │ Voice I/O      │   │ 9 VS commands         │   │ Writes, tests, commits    │  │
│  │ Personas       │   │ Build error AI fixes  │   │ 4 autonomy modes          │  │
│  │ History        │   │ Diff viewer           │   │ Human approval gate       │  │
│  └───────┬────────┘   └──────────┬────────────┘   └──────────────┬────────────┘  │
│          │                       │                               │               │
│          └───────────────────────┼───────────────────────────────┘               │
│                                  │                                               │
│                      ┌───────────▼────────────┐                                 │
│                      │   ARBITER ENGINE        │                                 │
│                      │   FastAPI · port 8001   │                                 │
│                      │   210+ REST endpoints   │                                 │
│                      │   12 LLM backends       │                                 │
│                      │   Module / Plugin bus   │                                 │
│                      └───────────┬─────────────┘                                 │
│                                  │                                               │
│          ┌───────────────────────┼────────────────────────┐                     │
│          │                       │                        │                     │
│  ┌───────▼──────┐   ┌────────────▼───────────┐   ┌───────▼──────────────────┐  │
│  │ PYTHON BRIDGE│   │  WPF HOSTAPP            │   │ STEAM SERVER ADMIN       │  │
│  │ port 8000    │   │  C#/.NET 8              │   │ Standalone FastAPI       │  │
│  │ Lightweight  │   │  Monaco IDE WebView2    │   │ SteamCMD wrapper         │  │
│  │ LLM proxy    │   │  WPF panels + tray      │   │ Role-based perms         │  │
│  └──────────────┘   └────────────────────────┘   │ AI health monitoring     │  │
│                                                   └──────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### Communication Protocols

| Connection | Protocol | Port |
|-----------|----------|------|
| WPF HostApp → ArbiterEngine | HTTP REST + WebSocket | 8001 |
| WPF HostApp → PythonBridge | HTTP REST | 8000 |
| VSIX Extension → ArbiterEngine | HTTP REST | 8001 |
| WPF MonacoIDE ↔ HostApp | WebView2 postMessage | in-process |
| ArbiterEngine → SteamServerAdmin | HTTP REST (internal) | 8002 |

---

## 3. Component Specifications

### 3.1 WPF HostApp

**Location**: `HostApp/`
**Technology**: C# / .NET 8 / WPF with `UseWindowsForms=true` (for NotifyIcon tray)

#### Windows

| Window | Purpose |
|--------|---------|
| `LauncherWindow` | Start-up mode picker; starts ArbiterEngine/PythonBridge subprocess |
| `IdeWindow` | Full-screen Monaco IDE via WebView2; native menu, toolbar, status bar, tray |
| `MainWindow` | Project list, basic chat, server health check |
| `ProjectWindow` | Per-project chat, file tree, git panel |
| `WorkspaceWindow` | Drag-and-drop workspace manager |
| `SettingsWindow` | All settings backed by `Config/settings.json` |

#### Key Subsystems

- **BuildManager** (`BuildInterface/BuildManager.cs`): orchestrates `dotnet`, `npm`, `cargo`, `python` builds.
- **GitManager** (`GitInterface/GitManager.cs`): LibGit2Sharp git operations.
- **VoiceManager** (`VoiceInterface/VoiceManager.cs`): TTS (System.Speech) + STT (Whisper).
- **Updater** (`Updater.cs`): GitHub Releases auto-update check.

#### Settings Storage
Settings live in `Config/settings.json`, loaded by `SettingsWindow` via path-walking up 6 directory levels to find the repo root.

#### RelayCommand Pattern
Keyboard shortcut bindings use a `RelayCommand` defined in `IdeWindow.xaml.cs`. All keyboard shortcuts register through this pattern.

---

### 3.2 ArbiterEngine (port 8001)

**Location**: `AIEngine/ArbiterEngine/server.py`
**Technology**: Python / FastAPI / Uvicorn

#### Boot Sequence

1. `setup_logging()` — rotating file handler at `logs/arbiter_engine/`
2. `ConfigLoader` loads `configs/*.json`
3. `ModuleLoader` scans `modules/` and registers tools
4. `PluginLoader` scans `plugins/` and registers plugins
5. `create_llm()` creates the configured LLM backend, wrapped with failover
6. `ArchiveManager` + `LibraryManager` start the knowledge watcher
7. FastAPI app starts with CORS middleware + timeout middleware

#### Module System

Modules live in `AIEngine/ArbiterEngine/modules/<name>/`. Each module exposes tools registered to `ToolRegistry`. Key modules:

| Module | Tools Exposed |
|--------|--------------|
| `issues/` | Issues CRUD with git-backed JSONL storage |
| (others) | Custom tools registered at runtime |

#### Plugin System

Plugins live in `AIEngine/ArbiterEngine/plugins/`. Loaded via `PluginLoader` at startup. Can register additional tools.

#### LLM Backends

Configured via `configs/config.json` key `agent.default_llm_backend`. Supported backends:

| Backend | Notes |
|---------|-------|
| `ollama` | Default; local models |
| `openai` | OpenAI API |
| `anthropic` | Anthropic Claude |
| `cohere` | Cohere |
| `huggingface` | HuggingFace Inference |
| `llama_cpp` | Local llama.cpp |
| `gpt4all` | Local GPT4All |
| + more | Via factory pattern |

Failover: if `agent.fallback_llm_backends` is set, `_build_failover_llm()` wraps the primary with automatic fallback.

#### Key Data Paths

| Data | Path |
|------|------|
| Workspace JSONL logs | `.arbiter/logs/workspace.jsonl` |
| Session snapshot | `AIEngine/ArbiterEngine/logs/session_snapshot.json` |
| Knowledge graph | `AIEngine/ArbiterEngine/logs/knowledge_graph.json` |
| Persona feedback | `AIEngine/ArbiterEngine/logs/persona_feedback.json` |
| Specialist agents | `AIEngine/ArbiterEngine/logs/specialist_agents.json` |
| Issues | `.arbiter/issues/<id>.json` |
| Budget tracking | `AIEngine/ArbiterEngine/logs/budget.json` |

---

### 3.3 PythonBridge (port 8000)

**Location**: `AIEngine/PythonBridge/fastapi_bridge.py`
**Technology**: Python / FastAPI / Uvicorn

Lightweight proxy mode that exposes the same REST contract as ArbiterEngine but with reduced functionality. Used when the full engine is not needed (e.g., CI environments). The WPF app can switch between ports 8000 and 8001 at launch.

---

### 3.4 Visual Studio VSIX Extension

**Location**: `VisualStudioExtension/`
**Technology**: C# / VSIX / VS 2022 SDK

#### Commands

| Command | Shortcut | Description |
|---------|---------|-------------|
| Ask Arbiter AI | Ctrl+Shift+A | Send selected code + question to chat |
| Explain Code | Ctrl+Shift+E | Explain the selection |
| Refactor | Ctrl+Shift+R | AI-guided refactor |
| Generate Tests | Ctrl+Shift+T | Generate unit tests |
| Fix Build Error | — | Triggered by build error detection |
| Add Docs | — | Insert XML doc comments |
| Review | — | Full review workflow |
| Inline Chat | — | Side-panel chat anchored to code position |
| Diff Viewer | — | Before/after diff of AI suggestions |

#### Architecture

- **ArbiterPackage**: MEF entry point; registers commands, initialises HTTP client.
- **ArbiterToolWindow**: Side-panel hosting the chat UI (WPF/WebView2).
- **CodeAnalyser**: Reads VS diagnostic events; feeds build errors to AI.
- **CompletionProvider**: Roslyn-based inline completions via ArbiterEngine `/ai/complete`.

---

### 3.5 SteamServerAdmin

**Location**: `Projects/SteamServerAdmin/`
**Technology**: Python / FastAPI; SteamCMD; optional React/Blazor web dashboard

#### Phases

| Phase | Scope |
|-------|-------|
| 0 — Scaffold | Config schema, logging, SteamCMD wrapper, workspace registration |
| 1 — Core Server Management | start/stop/restart/update, scheduled ops, RCON, multi-server |
| 2 — Permissions & Audit | Role tiers, audit log, whitelist, change notifications |
| 3 — REST API & Dashboard | Full REST + WebSocket + dark web UI |
| 4 — AI Health Monitoring | Log ingestion, threshold rules, autonomous action dispatch, Arbiter integration |

#### Config Schema (per server)

```json
{
  "server_id": "string",
  "app_id": "integer (Steam app ID)",
  "name": "string",
  "install_path": "string (absolute path)",
  "branch": "string (default: public)",
  "launch_args": "string",
  "max_players": "integer",
  "restart_schedule": "cron string or null",
  "update_schedule": "cron string or null",
  "rcon": {
    "host": "string",
    "port": "integer",
    "password": "string"
  },
  "roles": {
    "<steam_id>": "Admin|Moderator|Operator|Player"
  },
  "health_thresholds": {
    "max_error_rate_per_minute": "integer",
    "crash_keywords": ["array of strings"],
    "min_players_alert": "integer"
  }
}
```

---

## 4. Feature Specifications

### 4.1 Chat Engine

The chat engine is the core user interface for interacting with Arbiter AI.

#### Capabilities

| Feature | Endpoint | Description |
|---------|---------|-------------|
| Basic chat | `POST /chat` | Single-turn Q&A |
| Streaming chat | `GET /chat/stream` | SSE streaming response |
| Thread management | `POST /chat/thread` | Create/continue named threads |
| Branch conversations | `POST /chat/branch` | Fork a conversation at any point |
| Templates | `GET /chat/templates` | Pre-built prompt templates |
| Feedback | `POST /chat/feedback` | Rate responses (up/down) |
| Bookmarks | `POST /chat/bookmark` | Save important exchanges |
| Image analysis | `POST /chat/image` | Attach images to queries |
| File context | `POST /chat/context/file` | Attach file contents to chat |
| Code context | `POST /chat/context` | Attach code selection + file |
| Summarise | `POST /chat/summarise` | Summarise a conversation thread |
| Analytics | `GET /chat/analytics` | Usage stats per project |

#### Personas

Built-in personas (configurable in `configs/config.json`):
- `default` — General-purpose assistant
- `coder` — Code-focused, terse, no prose
- `reviewer` — Code review specialist
- `architect` — System design & scalability
- `teacher` — Explains concepts step-by-step
- `researcher` — Deep analysis, citations
- `creative` — Creative writing & brainstorming

Custom personas: `POST /persona/custom`; feedback loop via `POST /persona/feedback` + `POST /persona/adapt`.

#### Voice I/O

- TTS: `POST /voice/tts` — converts text to audio (system TTS or local model)
- STT: `POST /voice/stt` — transcribes audio file to text (Whisper)

#### History

- `GET /history/{project}` — paginated history
- `POST /history/{project}/export` — export to JSON/Markdown
- `GET /history/search` — full-text search across all history

---

### 4.2 Self-Build Loop

The self-build loop is Arbiter's autonomous development engine.

#### Workflow

```
roadmap.json
     │
     ▼
SelfBuildController.select_next_task()
     │  picks first pending task
     ▼
SelfBuildController.plan_task()
     │  LLM generates implementation plan
     ▼
SelfBuildController.implement_task()
     │  LLM writes code diff/patches
     ▼
SelfBuildController.test_task()
     │  runs relevant tests
     ▼
Human Approval Gate  (optional, depends on autonomy mode)
     │
     ▼
SelfBuildController.commit_task()
     │  git commit: "[arbiter-self-build] <task_id>: <title>"
     ▼
roadmap.json updated: task status → "done"
```

#### Autonomy Modes

| Mode | Description |
|------|-------------|
| `manual` | Each step requires explicit human trigger |
| `semi` | Plans automatically; pauses before commit |
| `auto` | Fully autonomous; human approval only for risky patches |
| `full` | Completely autonomous; no approvals |

#### Endpoints

| Endpoint | Method | Description |
|---------|--------|-------------|
| `/self-build/start` | POST | Start the loop |
| `/self-build/stop` | POST | Stop gracefully |
| `/self-build/status` | GET | Current status, active task, log tail |
| `/self-build/approve` | POST | Approve pending patch |
| `/self-build/reject` | POST | Reject pending patch with feedback |
| `/self-build/log` | GET | Full build log |
| `/self-build/next` | GET | Preview next task |

---

### 4.3 Archive & Library (RAG)

The Archive & Library system provides retrieval-augmented generation over the workspace.

- **ArchiveManager**: Watches `workspace/` for file changes; extracts and indexes content.
- **LibraryManager**: Manages the vector-like index; answers semantic queries.
- Endpoints: `GET /archive/list`, `POST /archive/query`, `GET /library/status`

---

### 4.4 Code Analysis Suite

Full static and AI-assisted code analysis.

| Endpoint | Analysis Type |
|---------|--------------|
| `POST /analysis/lint` | Pyflakes/eslint/etc. lint issues |
| `POST /analysis/complexity` | Cyclomatic complexity (radon) |
| `POST /analysis/duplicates` | Near-duplicate code detection |
| `POST /analysis/deps/security` | CVE scan via Safety/Grype |
| `POST /analysis/coverage` | Test coverage report parsing |
| `POST /analysis/profile` | Runtime profiling (cProfile/py-spy) |
| `POST /docs/generate` | AI-generated documentation |
| `POST /review/workflow` | Combined lint + complexity + AI review |

---

### 4.5 Workspace & Projects

Arbiter treats each directory as a "workspace" and each entry in `Projects/` as a managed project.

- `GET /workspace` — list workspace files
- `POST /workspace/open` — open a directory
- `GET /projects` — list all managed projects (reads `Projects/*/roadmap.json`)
- `GET /project/profile` — AI-generated project summary

---

### 4.6 Knowledge Graph

Semantic graph of code entities (files, functions, classes, modules) and their relationships.

- Built by `POST /knowledge/scan`
- Queried by `GET /knowledge/graph` and `GET /knowledge/search`
- Used automatically in AI context enrichment

---

### 4.7 Issues Tracker

Local git-backed issues tracker (no external dependencies).

- Issues stored as JSON at `.arbiter/issues/<id>.json`
- Every mutation auto-commits with `[arbiter-issue]` prefix
- REST: `POST /issues/create`, `GET /issues/list`, `GET /issues/{id}`, `POST /issues/close`, `POST /issues/comment`

---

### 4.8 Wiki Panel

The in-application wiki panel serves markdown documentation from `docs/wiki/`.

- `GET /wiki` — list all available wiki documents
- `GET /wiki/{filename}` — return raw markdown content for a document

The WPF `IdeWindow` renders wiki content via the Monaco/WebView2 panel using a markdown renderer. Documents are stored in `docs/wiki/*.md` and are human-editable.

---

### 4.9 Changelog Automation

Changelog entries are auto-generated from git commits that follow the `[arbiter-self-build]` prefix convention.

- `POST /changelog/generate` — scans git log, groups commits by task, writes entries to `docs/wiki/CHANGELOG.md`
- `GET /changelog` — return current CHANGELOG content

Format per entry:
```
## [auto] YYYY-MM-DD
- [task_id] commit message body
```

---

## 5. Integration Points

### 5.1 WPF ↔ ArbiterEngine

The WPF HostApp is the primary consumer of ArbiterEngine. All chat, self-build, analysis, and project operations are performed via HTTP to `localhost:8001`.

**Key flows**:
- **Chat**: `IdeWindow` sends `POST /chat`; streams SSE from `GET /chat/stream`.
- **Self-Build**: `IdeWindow` triggers `POST /self-build/start`; polls `GET /self-build/status`.
- **Code Actions**: VSIX forwards selection to `IdeWindow` → postMessage → `POST /ai/complete` or `/ai/review`.
- **Wiki Panel**: `IdeWindow` calls `GET /wiki/{doc}` and renders markdown.
- **Health Check**: LauncherWindow polls `GET /health` at startup.

### 5.2 VSIX ↔ ArbiterEngine

The VSIX extension connects directly to ArbiterEngine at port 8001 (configurable).

**Key flows**:
- **Inline completion**: `POST /ai/complete/context` with file + cursor context.
- **Explain/Refactor/Test**: `POST /chat` with specialized system prompt.
- **Build error fix**: `POST /ai/review` with diagnostic message.
- **Diff Viewer**: `POST /ai/diff` to get structured before/after diff.

### 5.3 ArbiterEngine ↔ SteamServerAdmin

When SteamServerAdmin is running (port 8002), ArbiterEngine bridges requests through:
- ArbiterEngine `/ssa/*` endpoints proxy to `localhost:8002`
- SteamServerAdmin events (crashes, updates) are written to Arbiter workspace log
- AI health analysis uses `POST /chat` with log context

### 5.4 ArbiterEngine ↔ Novaforge

Novaforge (the game project) integrates with Arbiter via:
- `Projects/Novaforge/roadmap.json` — self-build loop manages Novaforge tasks
- PCG and mech systems code generation via specialist agents
- Build integration via `BuildManager`

### 5.5 Self-Build ↔ All Components

The self-build loop has read/write access to all components:
- Reads `roadmap.json` (all projects)
- Writes to any source file in the workspace
- Runs builds (`dotnet build`, `npm run build`, `python -m pytest`)
- Commits via git with `[arbiter-self-build]` prefix
- Updates `roadmap.json` task statuses
- Creates issues via `/issues/create` when tests fail

---

## 6. Data Flow Diagrams

### Chat Request Flow

```
User types message in WPF/VSIX
        │
        ▼
POST /chat  {project, message, persona, history}
        │
        ▼
server.py chat handler
   ├── resolve persona system prompt
   ├── load project history
   ├── enrich context (Archive RAG, knowledge graph)
   └── call LLM.chat(messages)
             │
             ▼
        LLM backend (Ollama, etc.)
             │
             ▼
        Response streamed back (SSE) or returned as JSON
        │
        ▼
WPF renders in Monaco / chat panel
```

### Self-Build Flow

```
POST /self-build/start
        │
        ▼
SelfBuildController.run()
   ├── select_next_task() → reads roadmap.json
   ├── plan_task()        → LLM prompt: "Plan implementation of <task>"
   ├── implement_task()   → LLM prompt: "Write code for <plan>"
   ├── test_task()        → subprocess: run test suite
   ├── [await approval if mode requires it]
   └── commit_task()      → git commit + roadmap status update
        │
        ▼
GET /self-build/status → real-time progress
```

---

## 7. REST & WebSocket API Contract

See `docs/wiki/API_REFERENCE.md` for the full endpoint listing. Key groups:

| Group | Prefix | Count |
|-------|--------|-------|
| Chat | `/chat/` | 12 |
| AI | `/ai/` | 10 |
| Self-Build | `/self-build/` | 7 |
| Analysis | `/analysis/` | 6 |
| Knowledge | `/knowledge/` | 3 |
| Issues | `/issues/` | 5 |
| Wiki | `/wiki/` | 2 |
| Changelog | `/changelog/` | 2 |
| Workspace | `/workspace/`, `/project/` | 6 |
| Agents | `/agents/` | 3 |
| Persona | `/persona/` | 4 |
| Pair Programming | `/pair/` | 4 |
| Metrics & Budget | `/metrics`, `/budget/` | 5 |
| Health | `/health`, `/health/detailed` | 2 |
| Logging | `/log/` | 3 |
| WebSocket | `/ws/chat`, `/ws/servers/` | 2 |

---

## 8. LLM Backend Configuration

Configuration key: `agent.default_llm_backend` in `AIEngine/ArbiterEngine/configs/config.json`.

```json
{
  "agent": {
    "default_llm_backend": "ollama",
    "fallback_llm_backends": ["openai"],
    "model": "codellama:13b",
    "temperature": 0.2,
    "max_tokens": 4096,
    "timeout": 120
  }
}
```

Failover: if the primary backend times out or returns an error, `FailoverLLM` tries each backend in `fallback_llm_backends` in order.

**Blocking call fix**: All LLM calls inside async handlers use `asyncio.to_thread(_llm.chat, messages)` to avoid stalling the uvicorn event loop.

---

## 9. Security & Permissions

### API Security

ArbiterEngine currently runs on localhost only and does not implement authentication. When exposed externally (e.g., Docker with port mapping), use network-level security (firewall, VPN, reverse proxy with auth).

### SteamServerAdmin Role Tiers

| Role | Capabilities |
|------|-------------|
| Admin | Full control: start/stop/restart/update, role management, whitelist, all RCON commands |
| Moderator | kick/ban/say, mute, read logs |
| Operator | restart/update only, read status |
| Player | Read-only: server status |

### Issues Tracker

Issues are stored locally (no auth required) and git-committed. Each commit is signed with the `[arbiter-issue]` prefix.

---

## 10. Deployment Targets

| Target | Method | Notes |
|--------|--------|-------|
| Developer workstation (Windows) | WPF HostApp + ArbiterEngine | Primary target |
| Developer workstation (Linux/macOS) | ArbiterEngine headless + web UI | Cross-platform |
| Docker | `docker-compose up` | `Dockerfile` + `docker-entrypoint.sh` |
| CI/CD | ArbiterEngine headless | Cron self-build loop |
| Live game server | SteamServerAdmin standalone | Python service or Docker |
| Remote (LAN) | ArbiterEngine on server, browser client | Port 8001 accessible on LAN |

---

*This document is maintained automatically by the Arbiter self-build loop. To regenerate, trigger `POST /changelog/generate` or run the self-build loop.*
