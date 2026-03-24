# Arbiter — Project Roadmap

> **Machine-readable version:** [`roadmap.json`](roadmap.json) — drives the autonomous self-build loop.
> **Detailed phase breakdown:** [`docs/wiki/ROADMAP.md`](docs/wiki/ROADMAP.md)

---

## Current Status

**Version:** 1.13.0 | **All M0–M14 milestones + Phases 1–11 complete** ✅

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

## Completed Phases (1–7)

| Phase | Title | Key Additions | Status |
|-------|-------|---------------|--------|
| **Phase 1** | Platform Consolidation | Logging, wiki, shutdown prompt, README, ROADMAP.md | ✅ Done |
| **Phase 2** | Tooling Layer & AI Integration | Agent loop, VS inline/refactor, model routing, CodeGeeX | ✅ Done |
| **Phase 3** | Project-Aware Workspace Intelligence | /projects activate/health, workspace state, scaffold | ✅ Done |
| **Phase 4** | Development Agent Enhancement | git watch/review-commit, self-improve, tests/run | ✅ Done |
| **Phase 5** | Production & Deployment | Dockerfile, self-update, API keys + rate-limit, plugins | ✅ Done |
| **Phase 6** | Cross-Project Intelligence | commit-message AI, AI plan, workspace timeline, dependencies, snapshots, context/summary, cross-project search | ✅ Done |
| **Phase 7** | Observability & Developer Experience | /metrics, project activity feed, AI explain, workspace health, git blame-explain, project changelog | ✅ Done |
| **Phase 8** | Smart Automation & Workspace Productivity | /ai/project-refactor, /projects/{id}/docs, /workspace/todos, /ai/migrate, /projects/{id}/estimate, /projects/{id}/test-generate | ✅ Done |
| **Phase 9** | Advanced Collaboration & Knowledge Management | /ai/code-walkthrough, /projects/{id}/coverage-report, /workspace/notes, /projects/{id}/progress, /projects/{id}/roadmap/task, /workspace/summary | ✅ Done |
| **Phase 10** | Embedded AI & Zero-External-Dependency Local Inference | /ai/embedded/load, /ai/embedded/status, /ai/embedded/models, /ai/embedded/unload, llm/embedded.py (llama-cpp-python), /models/backends updated | ✅ Done |
| **Phase 11** | AI Code Intelligence & Semantic Workspace Search | /ai/semantic-search, /ai/fix, /projects/{id}/security-audit, /ai/context/build, /ai/rename-symbol, /workspace/ai-stats | ✅ Done |

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

*Last updated: 2026-03-24 — v1.13.0*
