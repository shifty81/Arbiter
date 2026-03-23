# Arbiter — Repository Directive

**Version:** 1.0  
**Date:** 2026-03-23  
**Status:** Active

---

## Project Identity

**Arbiter** is a self-hosted, fully offline, AI-powered development platform built as a first-class Windows application. It is not a chatbot wrapper — it is a controllable, self-iterating AI agent that integrates deeply into a developer's workflow across three pillars:

1. **Chat** — a rich, context-aware conversational interface with full development-lifecycle awareness
2. **Visual Studio Integration** — a native VSIX extension that brings Arbiter directly into Visual Studio 2022
3. **Self-Iteration** — an autonomous loop where Arbiter reads its own roadmap, writes code, tests, and commits improvements to itself

Everything runs locally. No cloud required. No telemetry. Your code never leaves your machine.

---

## New Project Direction

The project is moving from "Monaco IDE in a WPF shell" toward a **three-pillar platform** where each pillar is fully developed and tightly integrated:

```
┌─────────────────────────────────────────────────────────────────┐
│                        ARBITER PLATFORM                         │
├──────────────────┬───────────────────────┬──────────────────────┤
│   PILLAR 1       │    PILLAR 2            │    PILLAR 3          │
│   CHAT ENGINE    │    VISUAL STUDIO       │    SELF-ITERATION    │
│                  │    INTEGRATION         │                      │
│ Context-aware    │ Native VSIX extension  │ Reads own roadmap    │
│ multi-turn chat  │ Side panel in VS 2022  │ Plans & writes code  │
│ with full SDLC   │ Inline AI suggestions  │ Tests & commits      │
│ awareness        │ Tool windows           │ Reports progress     │
└──────────────────┴───────────────────────┴──────────────────────┘
```

The WPF host application and FastAPI backend remain the foundation. The Monaco IDE web UI remains available at `/gui/`. The new priority is to make all three pillars fully functional, deeply integrated, and production-ready.

---

## Architecture

```
ArbiterAI/
├── HostApp/                         # C# WPF Windows application (.NET 8)
│   ├── LauncherWindow               # Startup mode picker
│   ├── MainWindow                   # Project list and management
│   ├── ProjectWindow                # Per-project: chat, file tree, git
│   ├── IdeWindow                    # Monaco IDE via WebView2
│   ├── WorkspaceWindow              # Drag-and-drop workspace
│   ├── PdfViewerWindow              # Documentation viewer
│   ├── BuildInterface/              # Build/run/test automation
│   ├── GitInterface/                # LibGit2Sharp git operations
│   ├── VoiceInterface/              # TTS + STT
│   └── Themes/DarkTheme.xaml        # VS Code-inspired dark theme
│
├── AIEngine/
│   ├── PythonBridge/                # Primary backend — port 8000
│   │   ├── fastapi_bridge.py        # FastAPI server (1800+ lines)
│   │   ├── llm_interface.py         # Hardware-aware LLM loader
│   │   ├── persona_manager.py       # Persona system
│   │   ├── archive_manager.py       # Archive/codex indexing
│   │   ├── library_manager.py       # Library path management
│   │   ├── model_downloader.py      # HuggingFace auto-download
│   │   ├── static/                  # Chat web UI
│   │   └── gui/                     # Monaco IDE web UI
│   │
│   └── ArbiterEngine/               # Full agentic backend — port 8001
│       ├── server.py                # FastAPI (same API contract)
│       ├── core/                    # Agent, self-build, task runner
│       ├── llm/                     # 12 LLM backends
│       └── configs/config.toml      # Runtime configuration
│
├── VisualStudioExtension/           # VSIX project (NEW — Pillar 2)
│   ├── ArbiterVSIX.csproj
│   ├── ArbiterPackage.cs            # VS package entry point
│   ├── ChatToolWindow.cs            # Arbiter chat tool window
│   ├── InlineSuggestionProvider.cs  # Inline AI completions
│   ├── ArbiterCommands.cs           # VS command registrations
│   └── source.extension.vsixmanifest
│
├── Memory/                          # Persistent storage
│   ├── ConversationLogs/            # Per-project SQLite chat history
│   ├── snippets.json                # Saved code snippets
│   ├── notes.json                   # Per-project notes
│   └── Archive/archive.json         # Archive codex
│
├── Projects/                        # User project workspaces
│
├── roadmap.json                     # Master project roadmap
├── README.md                        # Public-facing documentation
├── Specs.md                         # Technical specifications
└── setup_arbiter.py                 # One-click setup script
```

---

## Development Principles

1. **Local-first** — all AI inference, storage, and tooling runs on the developer's machine
2. **Offline by default** — no internet connection required after initial setup
3. **No vendor lock-in** — support 12+ LLM backends; developer chooses their model
4. **Integration-first** — Arbiter works inside existing tools (Visual Studio, WPF IDE) rather than replacing them
5. **Self-improving** — Arbiter should be able to contribute to its own development
6. **Transparent** — all AI actions, code changes, and decisions are visible and reversible
7. **Permission-aware** — no destructive action executes without explicit approval in non-autonomous mode
8. **Dark-themed** — VS Code-inspired dark palette applied consistently everywhere

---

## Pillar 1 — Chat Engine

The chat system is the primary interface for all development assistance. Every chat feature must be context-aware and deeply integrated with the developer's current workspace.

### Core Chat Features

| Feature | Description | Priority |
|---------|-------------|----------|
| Context injection | Active file path, selected code, open tabs, project name auto-injected into every message | P0 |
| Streaming responses | Server-Sent Events / WebSocket streaming for real-time token output | P0 |
| Conversation history | Per-project SQLite persistence; full history loaded on project open | P0 |
| Persona selection | Arbiter / Coder / Teacher / Organizer per project; shapes system prompt and response style | P0 |
| Voice I/O | Push-to-talk STT (Whisper); TTS reads AI response aloud (pyttsx3 / System.Speech) | P0 |
| Code block extraction | AI responses with fenced code blocks get "Apply", "Copy", "Save Snippet" actions | P1 |
| Inline diff preview | When AI proposes a file edit, show a diff before applying | P1 |
| File attachment | Drag a file into chat to include its content as context | P1 |
| Selection context | Selected text in editor auto-populates chat context | P1 |
| Task creation | `/task Create a login page` — AI creates a task in the project roadmap | P1 |
| Build trigger | `/build`, `/run`, `/test` commands execute directly from chat | P1 |
| Git trigger | `/commit "message"`, `/push`, `/branch feature/x` from chat | P1 |
| Snippet save | `/save snippet <name>` stores a code block to `Memory/snippets.json` | P1 |
| Archive search | `/search <term>` queries the Archive codex and injects top results into context | P2 |
| Multi-turn tool calls | AI can call tools iteratively within a single conversation turn | P2 |
| Agent mode | `/agent <goal>` triggers the agentic loop: plan → code → test → commit | P2 |
| Markdown rendering | AI responses rendered as markdown with syntax-highlighted code blocks | P0 |
| Export chat | Export conversation as Markdown or PDF | P2 |
| Chat search | Full-text search across all conversation history | P2 |
| Custom personas | Developer defines custom system prompts for additional personas | P2 |

### Chat API Contract

All chat features are served by both backends (port 8000 and port 8001) under the same API:

```
POST /chat                    — standard chat message
POST /assistant/chat          — IDE-aware chat with file context
POST /assistant/chat/agentic  — triggers agentic plan→edit→test loop
GET  /history/{project}       — full conversation history
DELETE /history/{project}     — clear history
GET  /personas                — list available personas
POST /persona/{project}       — set active persona
GET  /persona/{project}       — get active persona
```

---

## Pillar 2 — Visual Studio Integration

A native VSIX extension for Visual Studio 2022 that embeds Arbiter's full chat and tooling capabilities directly into the IDE.

### Extension Components

| Component | Description |
|-----------|-------------|
| `ArbiterPackage` | VS Package entry point; initialises connection to Arbiter backend on startup |
| `ChatToolWindow` | Dockable tool window with full Arbiter chat UI (WebView2-hosted) |
| `InlineSuggestionProvider` | Roslyn-based inline AI completions triggered by `// Arbiter:` comments |
| `ArbiterCommands` | Command table: Ask Arbiter, Explain Selection, Fix Selection, Refactor, Generate Tests |
| `StatusBarIntegration` | Shows active LLM backend and server status in VS status bar |
| `SettingsPage` | Tools → Options → Arbiter: backend URL, API key, voice, persona |
| `OutputWindow` | Dedicated "Arbiter" output pane for agentic task logs |
| `ErrorListIntegration` | AI-suggested fixes appear in Error List next to compiler errors |

### VS Commands (right-click context menu + keyboard shortcuts)

```
Ask Arbiter About Selection        Ctrl+Shift+A
Explain This Code                  Ctrl+Shift+E
Fix This Error                     Ctrl+Shift+F
Refactor With Arbiter              Ctrl+Shift+R
Generate Unit Tests                Ctrl+Shift+T
Add Documentation                  Ctrl+Shift+D
Review This File                   Ctrl+Shift+V
Insert Code From Chat              Ctrl+Shift+I
Open Arbiter Chat Panel            Ctrl+Alt+A
```

### Integration Points

- **Document events** — when a file is saved or opened in VS, its path and content become available as chat context
- **Selection changed** — selected code is automatically available to Arbiter commands without copy-paste
- **Build events** — post-build events trigger Arbiter to summarise errors and suggest fixes
- **Solution events** — solution open/close updates Arbiter's active project context
- **Error list** — compiler and analysis errors are sent to Arbiter for AI-generated fix suggestions

### Backend Communication

The VSIX communicates with whichever Arbiter backend is running:

```
Default: http://127.0.0.1:8000  (ArbiterAI lightweight mode)
Engine:  http://127.0.0.1:8001  (Arbiter Engine full mode)
```

Backend URL is configurable in the extension settings page. The extension auto-detects which port is live on startup.

---

## Pillar 3 — Self-Iteration

Arbiter's most distinctive capability: the ability to read its own roadmap, pick the next pending task, write code to implement it, run tests, and commit the result — with human oversight at every step.

### Self-Build Loop Architecture

```
Self-Build Cycle:
┌─────────────────────────────────────────────────────────────────┐
│  1. READ roadmap.json → find next pending task                  │
│  2. PLAN implementation steps (AI generates a step list)        │
│  3. IDENTIFY files to create / modify                           │
│  4. WRITE code changes (AI generates diffs or full files)       │
│  5. VALIDATE syntax / compile check                             │
│  6. RUN tests (pytest / dotnet test / npm test)                 │
│  7. REVIEW results — if tests fail, iterate up to N times       │
│  8. COMMIT changes with structured commit message               │
│  9. UPDATE roadmap.json (mark task done, add notes)             │
│  10. REPORT to chat panel / IDE roadmap panel                   │
└─────────────────────────────────────────────────────────────────┘
```

### Self-Build Controls

| Mode | Behaviour |
|------|-----------|
| `Manual` | Arbiter suggests the next task but takes no action |
| `Assist` | Arbiter generates code changes but waits for approval before applying |
| `SemiAuto` | Arbiter applies code changes, but asks before committing |
| `FullAuto` | Arbiter plans, codes, tests, commits, and advances roadmap autonomously |
| `Locked` | Self-build loop is disabled |

### Self-Build API

```
POST /self-build/start           — start self-build loop (mode: assist/semiauto/fullauto)
POST /self-build/stop            — stop the loop
GET  /self-build/status          — current task, progress, loop state
POST /self-build/approve         — approve pending change in Assist/SemiAuto mode
POST /self-build/reject          — reject pending change (AI tries alternative)
GET  /self-build/log             — full self-build session log
```

### What Arbiter Can Self-Build

- Implement pending `roadmap.json` tasks (both in the main repo and per-project)
- Add new API endpoints to `fastapi_bridge.py` or `server.py`
- Add new tool modules to `AIEngine/ArbiterEngine/modules/`
- Add new chat features to `AIEngine/PythonBridge/gui/app.js`
- Write unit tests for new code
- Refactor existing code toward a stated architectural goal
- Update documentation (README.md, roadmap.json, Specs.md)

### Safety Constraints

- Self-build never pushes to remote without explicit approval
- Self-build never modifies `configs/config.toml`, `settings.json`, or `.env` in FullAuto mode
- All generated diffs are stored in `AIEngine/ArbiterEngine/logs/` before application
- Self-build can be halted at any point with `POST /self-build/stop`

---

## Implementation Roadmap Summary

| Milestone | Focus | Status |
|-----------|-------|--------|
| M0 — Foundation | WPF shell, Python bridge, chat, voice, personas, git, build/run/test | ✅ Done |
| M1 — IDE Integration | Monaco IDE, WebView2 embedding, File CRUD, AI code actions, WebSocket streaming | ✅ Done |
| M2 — Arbiter Engine | 12 LLM backends, agentic loop, module/plugin system, self-build infrastructure | 🔄 In Progress |
| M3 — Archive & Library | Knowledge codex, background indexer, keyword search, context injection | 🔄 In Progress |
| M4 — WPF IDE Completion | Full native IDE client, status bar, menu bar, keyboard shortcuts, multi-window | �� Planned |
| M5 — Advanced Chat & AI | RAG search, voice-in-IDE, AI code review, completions, session memory | 📋 Planned |
| M6 — Visual Studio Integration | VSIX extension, chat panel, inline suggestions, VS commands, settings page | 📋 Planned |
| M7 — Self-Iteration | Full self-build loop (4 modes), roadmap-driven autonomous development | 📋 Planned |
| M8 — Distribution | NSIS installer, auto-update, plugin marketplace, CLI, Docker | 📋 Planned |

See `roadmap.json` for full task-level breakdown.

---

## Technology Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| Windows UI | C# WPF / .NET 8 | Main application host |
| VS Extension | C# VSIX / Visual Studio SDK | Pillar 2 integration |
| AI Backend | Python FastAPI | Ports 8000 (bridge) / 8001 (engine) |
| LLM Inference | llama-cpp-python (GGUF) | Local inference |
| LLM Alternatives | Ollama, OpenAI, Anthropic, Gemini, LM Studio, LocalAI, OpenWebUI, Tabby | 12 backends via factory |
| TTS | pyttsx3 / System.Speech | Voice output |
| STT | Whisper / Windows Speech | Voice input |
| Editor (Web) | Monaco Editor | Embedded via WebView2 |
| Terminal (Web) | xterm.js | PTY via WebSocket |
| Git | LibGit2Sharp (C#) + GitPython (Python) | Full git operations |
| Vector Search | ChromaDB / FAISS | RAG (M5) |
| Agent Framework | Custom agentic loop | ArbiterEngine core |
| Memory | SQLite (conversations) + JSON (config, archive) | All local files |
| Testing | pytest (Python) + xUnit (C#) | Per-project test runners |

---

## File Conventions

- All Python source files use snake_case naming
- All C# files use PascalCase naming
- All JSON config files are lowercase with underscores
- Markdown files use Title Case with spaces
- All new API endpoints are added to both `fastapi_bridge.py` (port 8000) and `server.py` (port 8001) to maintain API contract parity
- All new VSIX components are registered in `ArbiterPackage.cs`
- Self-build logs go to `AIEngine/ArbiterEngine/logs/self_build/`
- Per-project data goes to `Memory/ConversationLogs/<project_name>.db`

---

## Contribution Notes

This is an active solo project. The self-build loop (Pillar 3) means Arbiter itself contributes code back to the repository. All AI-generated commits are tagged with `[arbiter-self-build]` in the commit message so they are distinguishable from human commits.

The development priority order is:
1. Complete M2 (Arbiter Engine) and M3 (Archive) in-progress work
2. Build M6 (Visual Studio Integration) — highest new priority
3. Complete M4 (WPF IDE) finishing touches
4. Build M7 (Self-Iteration) full pipeline
5. Build M5 (Advanced AI) capabilities
6. Build M8 (Distribution) for release
