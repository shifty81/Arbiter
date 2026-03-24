# Arbiter — Project Roadmap

> **Machine-readable version:** [`roadmap.json`](roadmap.json) — drives the autonomous self-build loop.
> **Detailed phase breakdown:** [`docs/wiki/ROADMAP.md`](docs/wiki/ROADMAP.md)

---

## Current Status

**Version:** 1.1.0 | **All M0–M14 milestones complete** ✅

---

## Completed Milestones

| # | Milestone | Key Features | Status |
|---|-----------|-------------|--------|
| **M0** | Foundation | WPF shell, FastAPI bridge, chat, voice, personas, git, build/run/test | ✅ |
| **M1** | IDE Integration | Monaco IDE, WebView2, File CRUD, AI code actions, WebSocket streaming | ✅ |
| **M2** | Arbiter Engine | 12 LLM backends, agentic loop, module/plugin system, self-build infra | ✅ |
| **M3** | Archive & Library | Knowledge codex, background indexer, BM25 search, context injection | ✅ |
| **M4** | WPF IDE | Native client, status bar, keyboard shortcuts, tray icon, multi-window | ✅ |
| **M5** | Advanced Chat | RAG, slash commands, inline diff, multi-agent, voice-in-IDE, dep scan | ✅ |
| **M6** | VS Integration | VSIX, chat panel, inline completions, 9 commands, build event hooks | ✅ |
| **M7** | Self-Iteration | Autonomous self-build loop, 4 autonomy modes, roadmap-driven | ✅ |
| **M8** | Distribution | Installer, auto-update, plugin marketplace, CLI, Docker, cloud sync | ✅ |
| **M9** | Productivity | Scaffold, docgen, refactor, Docker IDE, task queue, API client, CI, cron | ✅ |
| **M10** | Enhanced Chat | Branching, templates, feedback, multi-modal, SSE, threads, analytics | ✅ |
| **M11** | Advanced AI | Multi-model routing, agents, code-gen, knowledge graph, pair programming | ✅ |
| **M12** | Logging & Issues | JSONL workspace logs, crash capture, rotating files, issues tracker | ✅ |
| **M13** | Reliability | asyncio fix, timeout middleware, health, LRU cache, WS chat, LLM failover | ✅ |
| **M14** | Code Quality | Lint, dep security, complexity, duplicates, docgen, coverage, profiling | ✅ |

---

## Active Phases (Implementation Plan)

The following phases implement the long-term vision from the project's implementation plan,
combining AI tooling, server management, game systems, and development automation
into one cohesive platform.

### Phase 1 — Platform Consolidation *(In Progress)*

| Task | Description | Status |
|------|-------------|--------|
| P1-1 | Per-system logging — `logs/<system>/` at repo root | ✅ Done |
| P1-2 | Comprehensive docs wiki (`docs/wiki/`) | ✅ Done |
| P1-3 | Server shutdown prompt — keep live or shut down on app close | ✅ Done |
| P1-4 | Enhanced README banner with tool icons and roadmap | ✅ Done |
| P1-5 | ROADMAP.md as user-facing roadmap document | ✅ Done |
| P1-6 | Master Design Bible (`docs/design/MASTER_DESIGN_BIBLE.md`) | 🔜 Next |
| P1-7 | In-application Wiki panel from `docs/wiki/` | 🔜 Planned |
| P1-8 | Changelog automation from git log | 🔜 Planned |

### Phase 2 — Tooling Layer & AI Integration *(Planned)*

| Task | Description | Status |
|------|-------------|--------|
| P2-1 | Unified WPF UI for all editor tools | 🔜 Planned |
| P2-2 | Deeper VS Code / Visual Studio plugin integration | 🔜 Planned |
| P2-3 | ArbiterAI agent for automated coding, asset iteration, PCG | 🔜 Planned |
| P2-4 | Open-source model integration (Ollama, CodeGeeX) | 🔜 Planned |

### Phase 3 — Server Management System *(Planned)*

| Task | Description | Status |
|------|-------------|--------|
| P3-1 | SteamServerAdmin — start/stop/restart/update servers autonomously | 🔜 Planned |
| P3-2 | Role-based permissions (Admin, Moderator, Operator, Player) | 🔜 Planned |
| P3-3 | Permission audit logging and change notifications | 🔜 Planned |
| P3-4 | AI health monitoring — auto-restart on threshold breach | 🔜 Planned |
| P3-5 | Server dashboard in Tooling Layer / Monaco IDE | 🔜 Planned |

### Phase 4 — Game Systems & Procedural Generation *(Planned)*

| Task | Description | Status |
|------|-------------|--------|
| P4-1 | Mech suit systems — tiered upgrades (Reactor, Armor, Weapons, Cockpit) | 🔜 Planned |
| P4-2 | Visual propagation — upgrades affect interior/exterior aesthetics | 🔜 Planned |
| P4-3 | PCG room/interior/exterior generation with modular asset placement | 🔜 Planned |
| P4-4 | PCG ↔ Mech integration — upgrade tier drives generation complexity | 🔜 Planned |

### Phase 5 — Development Agent Integration *(Planned)*

| Task | Description | Status |
|------|-------------|--------|
| P5-1 | Repo monitoring — AI watches commits and suggests/implements changes | 🔜 Planned |
| P5-2 | PCG coherence checker — ensures game assets stay consistent | 🔜 Planned |
| P5-3 | Automated code → test → asset placement → AI feedback loop | 🔜 Planned |
| P5-4 | Server monitoring automation — AI triggers scripts from logs | 🔜 Planned |

### Phase 6 — Integration & Testing *(Planned)*

| Task | Description | Status |
|------|-------------|--------|
| P6-1 | Tooling Layer ↔ ArbiterAI ↔ Visual Studio cross-system tests | 🔜 Planned |
| P6-2 | Game systems ↔ PCG ↔ Mech logic validation suite | 🔜 Planned |
| P6-3 | Server monitoring ↔ Admin tools ↔ AI agent E2E tests | 🔜 Planned |

### Phase 7 — Deployment & Scaling *(Planned)*

| Task | Description | Status |
|------|-------------|--------|
| P7-1 | Deploy Tooling Layer and Dev Agent to developer machines | 🔜 Planned |
| P7-2 | Deploy server admin scripts to live servers | 🔜 Planned |
| P7-3 | Full AI oversight for continuous project iteration | 🔜 Planned |
| P7-4 | Analytics dashboards for AI-driven optimisation | 🔜 Planned |

---

## How the Roadmap Drives Development

`roadmap.json` is read by the self-build loop on every session start. Tasks with
`status: "pending"` are processed in milestone order. After each task completes,
the roadmap is updated automatically with `status: "done"`.

To add your own tasks, edit `roadmap.json` or use the **Roadmap** panel in the
Monaco IDE. See [Self-Build Loop](docs/wiki/SELF_BUILD.md) for details.

---

*Last updated: 2026-03-24*
