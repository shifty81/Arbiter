# Changelog

All notable changes to Arbiter are documented here.

---

## [1.1.0] — 2026-03-24

### Added
- **Per-system logging** — Each subsystem now writes to its own subfolder under
  `logs/` at the repo root (`arbiter_engine/`, `python_bridge/`, `host_app/`,
  `vs_extension/`, `self_build/`).
- **Comprehensive documentation wiki** — `docs/wiki/` with Architecture, Getting
  Started, Configuration, API Reference, Logging, Self-Build, VS Extension, Chat
  Engine, Monaco IDE, Roadmap, Changelog, Contributing, and Troubleshooting guides.
- **Server shutdown prompt** — When closing the WPF app, users are now asked
  whether to shut down managed servers or leave them running for remote chat access.
- **Enhanced README banner** — Tool icons, roadmap section directly below the
  banner, and updated milestone badges.
- **ROADMAP.md** — User-facing roadmap document covering all 7 phases from the
  implementation plan (Phase 1: Consolidation → Phase 7: Deployment & Scaling).
- **`setup_system_logging()` API** — New function in `core/logger.py` for subsystems
  to set up dedicated rotating log files with a single call.
- **M14** — Intelligent Code Quality & Security Analysis: `/analysis/lint`,
  `/analysis/deps/security`, `/analysis/complexity`, `/analysis/duplicates`,
  `/docs/generate`, `/analysis/coverage`, `/analysis/profile`, `/review/workflow`.

### Changed
- `server.py` — log file now written to `logs/arbiter_engine/arbiter_engine.log`
  (repo-level) instead of the engine's local `logs/` directory.
- `core/logger.py` — `setup_logging()` now defaults to the repo-level log path
  when no explicit `log_file` argument is given.
- `App.xaml.cs` — `App_Exit` now prompts the user before terminating server
  processes instead of always killing them silently.

---

## [1.0.0] — 2026-03-23

### Added
- **M13** — Reliability, Performance & Real-time Enhancement:
  - `asyncio.to_thread()` fix for server crash during streaming AI responses
  - Timeout middleware (configurable per-endpoint)
  - Enhanced `/health` endpoint with model status and uptime
  - LRU cache for repeated AI completions
  - WebSocket `/ws/chat` for real-time token streaming
  - Budget tracking per project
  - `/metrics` Prometheus-compatible endpoint
  - LLM failover to secondary backend on primary failure

---

## [0.9.0] — 2026-03-22

### Added
- **M12** — Logging & Issues Tracking:
  - Workspace JSONL structured logging (`write_workspace_log`, `read_workspace_log`)
  - Crash capture (`capture_crash`) with full traceback in log entry
  - Rotating file handlers in `setup_logging()` (5 MB, 5 backups)
  - Local git-backed issues tracker (`modules/issues/`)
  - REST API: `/issues/create`, `/issues/list`, `/issues/{id}`, `/issues/close`, `/issues/comment`

---

## [0.8.0] — 2026-03-21

### Added
- **M10** — Enhanced Chat & Conversational AI (10 new endpoints):
  `/chat/branch`, `/chat/templates`, `/chat/feedback`, `/chat/bookmark`,
  `/chat/image`, `/chat/context/file`, `/chat/stream` (SSE), `/chat/thread`,
  `/chat/analytics`, `/chat/summarize`
- **M11** — Advanced AI Intelligence (8 new endpoints):
  `/ai/route`, `/agents/specialist`, `/ai/generate/from-requirements`,
  `/knowledge/scan`, `/knowledge/graph`, `/knowledge/search`,
  `/ai/tests/generate`, `/search/semantic`, `/persona/feedback`,
  `/persona/adapt`, `/pair/start`, `/pair/analyze`

---

## [0.7.0] — 2026-03-20

### Added
- **M9** — Productivity & Integration (10 tasks):
  - Scaffold system (module/plugin/test boilerplate)
  - AI documentation generator
  - Regex/symbol refactor engine
  - Docker IDE integration
  - Persistent task queue
  - Built-in API client
  - AI brainstorm sessions
  - Test runner with report storage
  - CI integration
  - Cron scheduler and deployment manager

---

## [0.6.0] — 2026-03-18

### Added
- **M8** — Distribution:
  - Inno Setup 6 Windows installer
  - GitHub Releases auto-update (Updater.cs)
  - Plugin marketplace
  - VS Marketplace CI/CD publishing (VSIX)
  - CLI (`arbiter build / chat / archive / self-build`)
  - Docker + docker-compose one-command deployment
  - Cross-platform evaluation (CROSSPLATFORM.md)
  - Cloud sync (AES-256-GCM encrypted backup to S3/B2/local)

---

## [0.5.0]

### Added
- **M7** — Self-Iteration:
  - `SelfBuildController` — full roadmap-driven autonomous pipeline
  - Four autonomy modes: Manual / Assist / SemiAuto / FullAuto
  - Task planning, file identification, code generation (unified diff)
  - Python AST + dotnet build validation
  - Iteration loop (retry up to 3×)
  - Structured commit messages `[arbiter-self-build]`
  - Roadmap auto-update after task completion
  - Safety constraints (protected files in FullAuto)
  - VSIX self-build support

---

## [0.4.0]

### Added
- **M6** — Visual Studio Integration:
  - VSIX AsyncPackage with backend auto-detect
  - Dockable Arbiter chat panel (WebView2)
  - Roslyn inline AI completions (`// Arbiter:` trigger)
  - 9 VS commands with keyboard shortcuts
  - Document / solution / build event handlers
  - AI fix suggestions in VS Error List
  - Active LLM backend in VS status bar
  - Dedicated "Arbiter AI" output pane
  - Tools → Options → Arbiter AI settings page
  - Self-build status panel in VS

---

## [0.3.0]

### Added
- **M5** — Advanced Chat:
  - RAG over Archive codex (BM25 keyword + context injection)
  - Slash commands (`/build`, `/run`, `/test`, `/commit`, `/task`, `/agent`, `/search`)
  - Inline diff preview before AI applies changes
  - Multi-agent orchestration
  - Voice input in IDE (Whisper)
  - Dependency vulnerability scanning
  - Session memory (persistent key-value store per project)
  - Chat export (Markdown)
  - Full-text search across all history

---

## [0.2.0]

### Added
- **M4** — WPF IDE:
  - Full native client with status bar, menu bar, keyboard shortcuts
  - System tray icon (minimise to background)
  - Multi-window support
  - Dark title bar (WinAPI DWM)
- **M3** — Archive & Library:
  - Knowledge codex (`Memory/Archive/archive.json`)
  - Background BM25 indexer
  - Context injection from archive results
  - Archive export as Markdown

---

## [0.1.0]

### Added
- **M0** — Foundation:
  - C# WPF application shell (LauncherWindow, MainWindow, ProjectWindow)
  - FastAPI Python bridge (port 8000)
  - ChatGPT-style web UI
  - LLM loading (hardware-aware: llama.cpp / Ollama / OpenAI)
  - Voice output TTS (pyttsx3 / System.Speech)
  - Voice input STT (Whisper / Windows Speech)
  - Persona system
  - SQLite conversation history
  - Git integration (LibGit2Sharp / GitPython)
  - Build / run / test (dotnet / npm / cargo / python auto-detect)
  - GGUF model download (HuggingFace Hub)
  - Dark VS Code-inspired theme
- **M1** — IDE Integration:
  - Monaco IDE web UI via WebView2
  - PDF viewer window
  - File CRUD API
  - AI code actions (explain/fix/refactor/docstring/tests)
  - WebSocket streaming build output
  - Git REST API
  - AI assistant chat in IDE
  - Module/plugin scaffolding
- **M2** — Arbiter Engine:
  - Full agentic FastAPI server (port 8001)
  - 12 LLM backend adapters
  - Module loader, plugin loader, tool registry, permission system
  - Agentic plan→edit→test loop
  - Self-build infrastructure
