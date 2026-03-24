# Roadmap

Arbiter is developed against a public roadmap. The machine-readable version
at `roadmap.json` drives the self-build loop. This document is the human-readable
view combining completed milestones, in-progress work, and the long-term vision
from the project's implementation plan.

---

## Project Vision

Arbiter is evolving into a **multi-discipline AI development platform** spanning:

1. **AI-Powered Development Tooling** — Chat Engine, VS Integration, Self-Iteration
2. **Server Management System** — autonomous server admin for game/application servers
3. **Procedural Content Generation** — AI-assisted game asset and room generation
4. **Mech Suit Systems** — tiered upgrade systems with reactive visual changes
5. **Development Agent** — AI overseer that monitors repos and implements changes autonomously

---

## Completed Milestones

| Milestone | Description | Status |
|-----------|-------------|--------|
| **M0** — Foundation | WPF shell, FastAPI bridge, chat UI, LLM loading, voice I/O, personas, SQLite history, git, build/run/test | ✅ Complete |
| **M1** — IDE Integration | Monaco IDE, WebView2, File CRUD, AI code actions, WebSocket streaming | ✅ Complete |
| **M2** — Arbiter Engine | 12 LLM backends, agentic loop, module/plugin system, self-build infra | ✅ Complete |
| **M3** — Archive & Library | Knowledge codex, background indexer, keyword search, context injection | ✅ Complete |
| **M4** — WPF IDE | Full native client, status bar, menu bar, keyboard shortcuts, multi-window, tray icon | ✅ Complete |
| **M5** — Advanced Chat | RAG, slash commands, inline diff, multi-agent, voice-in-IDE, dependency scan | ✅ Complete |
| **M6** — Visual Studio Integration | VSIX extension, chat panel, inline completions, 9 commands, settings, build events | ✅ Complete |
| **M7** — Self-Iteration | Autonomous self-build loop, 4 autonomy modes, roadmap-driven, VSIX self-build | ✅ Complete |
| **M8** — Distribution | Inno Setup installer, auto-update, plugin marketplace, CLI, Docker, cloud sync | ✅ Complete |
| **M9** — Productivity & Integration | Scaffold, docgen, refactor engine, Docker IDE, task queue, API client, test runner, CI, cron, deploy | ✅ Complete |
| **M10** — Enhanced Chat & AI | Chat branching, templates, feedback, multi-modal input, smart context, bookmarks, SSE streaming, threads, analytics, summarisation | ✅ Complete |
| **M11** — Advanced AI Intelligence | Multi-model routing, agents marketplace, code gen from requirements, semantic search, knowledge graph, test intelligence, adaptive personas, pair programming | ✅ Complete |
| **M12** — Logging & Issues Tracking | Workspace JSONL logging, crash capture, rotating log files, local git-backed issues tracker | ✅ Complete |
| **M13** — Reliability, Performance & Real-time | asyncio.to_thread() fix, timeout middleware, enhanced health, LRU cache, WebSocket /ws/chat, budget tracking, /metrics, LLM failover | ✅ Complete |
| **M14** — Code Quality & Security Analysis | Lint API, dependency security audit, complexity analysis, duplicate detection, doc generation, coverage, profiling, review workflow | ✅ Complete |

---

## Active Roadmap — Phase 1: Platform Consolidation

*Goal: consolidate all subsystems under one cohesive structure with uniform
conventions, documentation, and tooling.*

| Task | Description | Status |
|------|-------------|--------|
| **P1-1** | Consolidated per-system logging (top-level `logs/` subfolders) | ✅ Done |
| **P1-2** | Comprehensive wiki documentation (`docs/wiki/`) | ✅ Done |
| **P1-3** | Server shutdown prompt — keep live or shut down | ✅ Done |
| **P1-4** | Enhanced README banner with tool icons and inline roadmap | ✅ Done |
| **P1-5** | ROADMAP.md as user-facing roadmap document | ✅ Done |
| **P1-6** | Master Design Bible (`docs/design/MASTER_DESIGN_BIBLE.md`) | 🔜 Next |
| **P1-7** | In-application Wiki panel populated from `docs/wiki/` | 🔜 Planned |
| **P1-8** | Changelog automation — generate from git log | 🔜 Planned |

---

## Phase 2: Tooling Layer & AI Integration

*Goal: single interface for AI-assisted development across all project types.*

| Task | Description | Status |
|------|-------------|--------|
| **P2-1** | Unified WPF UI for all editor tools (no external UI deps) | 🔜 Planned |
| **P2-2** | Deepen VS Code / Visual Studio plugin integration | 🔜 Planned |
| **P2-3** | ArbiterAI agent for automated coding, asset iteration, PCG, system debugging | 🔜 Planned |
| **P2-4** | Open-source model integration (Ollama, CodeGeeX, etc.) | 🔜 Planned |

---

## Phase 3: Server Management System

*Goal: autonomous server administration for game and application servers.*

| Task | Description | Status |
|------|-------------|--------|
| **P3-1** | SteamServerAdmin — start/stop/restart/update servers autonomously | 🔜 Planned |
| **P3-2** | Role-based permissions (Admin, Moderator, Operator, Player) | 🔜 Planned |
| **P3-3** | Permission audit logging and change notifications | 🔜 Planned |
| **P3-4** | AI health monitoring — auto-restart on threshold breach | 🔜 Planned |
| **P3-5** | Server dashboard integrated into Tooling Layer / Monaco IDE | 🔜 Planned |

---

## Phase 4: Game Systems & Procedural Generation

*Goal: AI-assisted PCG for rooms/interiors and mech suit upgrade systems.*

| Task | Description | Status |
|------|-------------|--------|
| **P4-1** | Mech suit systems — tiered upgrades (Reactor, Armor, Weapons, Cockpit) | 🔜 Planned |
| **P4-2** | Visual propagation — upgrades affect interior/exterior aesthetics | 🔜 Planned |
| **P4-3** | PCG room/interior/exterior generation with modular asset placement | 🔜 Planned |
| **P4-4** | PCG ↔ Mech integration — upgrade tier drives generation complexity | 🔜 Planned |

---

## Phase 5: Development Agent Integration

*Goal: ArbiterAI as a full-time repo overseer and automation agent.*

| Task | Description | Status |
|------|-------------|--------|
| **P5-1** | Repo monitoring — AI watches for commits and suggests changes | 🔜 Planned |
| **P5-2** | PCG coherence checker — ensures game assets stay consistent | 🔜 Planned |
| **P5-3** | Automated code → test → asset placement → AI feedback loop | 🔜 Planned |
| **P5-4** | Server monitoring automation — AI triggers scripts from logs | 🔜 Planned |

---

## Phase 6: Integration & Testing

| Task | Description | Status |
|------|-------------|--------|
| **P6-1** | Tooling Layer ↔ ArbiterAI ↔ Visual Studio cross-system tests | 🔜 Planned |
| **P6-2** | Game systems ↔ PCG ↔ Mech logic validation suite | 🔜 Planned |
| **P6-3** | Server monitoring ↔ Admin tools ↔ AI agent E2E tests | 🔜 Planned |

---

## Phase 7: Deployment & Scaling

| Task | Description | Status |
|------|-------------|--------|
| **P7-1** | Deploy Tooling Layer and Dev Agent to developer machines | 🔜 Planned |
| **P7-2** | Deploy server admin scripts to live servers | 🔜 Planned |
| **P7-3** | Full AI oversight for continuous project iteration | 🔜 Planned |
| **P7-4** | Analytics dashboards for AI-driven optimisation | 🔜 Planned |

---

## Long-Term Vision

> Arbiter becomes a **persistent AI collaborator** that:
> - Lives inside your development environment
> - Understands every subsystem in your project
> - Monitors code quality, server health, and game asset consistency
> - Implements improvements autonomously (with your approval)
> - Learns your preferences and adapts over time
> - Never requires the cloud — runs entirely on your machine

---

## Adding Your Own Tasks

Edit `roadmap.json` or use the Roadmap panel in the Monaco IDE to add tasks.
The self-build loop will pick them up automatically in the next session.

See [Self-Build Loop](SELF_BUILD.md) for details on how to write effective
task descriptions that produce high-quality generated code.
