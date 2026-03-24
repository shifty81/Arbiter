# Arbiter — Project Roadmap

> **Machine-readable version:** [`roadmap.json`](roadmap.json) — drives the autonomous self-build loop.
> **Detailed phase breakdown:** [`docs/wiki/ROADMAP.md`](docs/wiki/ROADMAP.md)

---

## Current Status

**Version:** 1.8.0 | **All M0–M14 milestones + Phases 1–5 complete** ✅ | **Phase 6 active** 🔄

---

## Completed Milestones (M0–M14)

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

## Completed Phases (1–5)

| Phase | Title | Status |
|-------|-------|--------|
| **Phase 1** | Platform Consolidation | ✅ Done |
| **Phase 2** | Tooling Layer & AI Integration | ✅ Done |
| **Phase 3** | Project-Aware Workspace Intelligence | ✅ Done |
| **Phase 4** | Development Agent Enhancement | ✅ Done |
| **Phase 5** | Production & Deployment | ✅ Done |

---

## Active Phase

### Phase 6 — Cross-Project Intelligence 🔄

New Arbiter API capabilities extending the platform's awareness across all managed project
workspaces.  All Phase 6 work is in `AIEngine/ArbiterEngine/server.py`.

| Task | Endpoint | Description | Status |
|------|----------|-------------|--------|
| **PA6-1** | `POST /ai/commit-message` | diff + context → AI conventional commit message | 🔄 In Progress |
| **PA6-2** | `POST /ai/plan` | natural-language goal → structured task list | 🔄 In Progress |
| **PA6-3** | `GET /workspace/timeline` | unified git commit timeline across all Projects/ | 🔄 In Progress |
| **PA6-4** | `GET /projects/{id}/dependencies` | parse requirements.txt / package.json / .csproj / go.mod / Cargo.toml | 🔄 In Progress |
| **PA6-5** | `POST /workspace/snapshot` · `GET /workspace/snapshots` · `POST /workspace/snapshots/{id}/restore` | named workspace state snapshots | 🔄 In Progress |
| **PA6-6** | `POST /projects/{id}/context/summary` | AI-generated compressed project context for fast injection | 🔄 In Progress |
| **PA6-7** | `GET /projects/search` | full-text search across all files in all managed project workspaces | 🔄 In Progress |

---

## Managed Projects

Arbiter manages the following external projects as first-class workspaces from within the
running application. Each has its own `roadmap.json` inside `Projects/` and is driven by
the same chat engine, self-build loop, and tooling as Arbiter itself.

**These projects are developed by Arbiter while it is running — not by direct repo contributions.**

| Project | Type | Summary | Roadmap |
|---------|------|---------|---------|
| **Novaforge** | Game Development | Atlas Core+ECS engine, modular mech suit systems, AI-driven PCG | [`Projects/Novaforge/roadmap.json`](Projects/Novaforge/roadmap.json) |
| **SteamServerAdmin** | Server Administration | Autonomous Steam game server lifecycle management, role permissions, AI health monitoring | [`Projects/SteamServerAdmin/roadmap.json`](Projects/SteamServerAdmin/roadmap.json) |

---

## How the Roadmap Drives Development

`roadmap.json` is read by the self-build loop on every session start. Tasks with
`status: "pending"` are processed in phase/milestone order. After each task completes,
the roadmap is updated automatically with `status: "done"`.

To add your own tasks, edit `roadmap.json` or use the **Roadmap** panel in the
Monaco IDE. See [Self-Build Loop](docs/wiki/SELF_BUILD.md) for details.

---

*Last updated: 2026-03-24*
