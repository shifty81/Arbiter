# Novaforge — Master Design Bible

> **Version:** 0.2.0  
> **Last updated:** 2026-03-24  
> **Maintained by:** Arbiter AI (ArbiterEngine + PythonBridge)

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
3. [Tooling Layer](#3-tooling-layer)
4. [AI Integration (ArbiterAI)](#4-ai-integration-arbiterai)
5. [Game Systems — Atlas Core + ECS](#5-game-systems--atlas-core--ecs)
6. [Mech Suit Upgrade System](#6-mech-suit-upgrade-system)
7. [Procedural Content Generation (PCG)](#7-procedural-content-generation-pcg)
8. [Server Administration (SteamServerAdmin)](#8-server-administration-steamserveradmin)
9. [Remote Web Interface](#9-remote-web-interface)
10. [AI Development Agent](#10-ai-development-agent)
11. [Integration Points](#11-integration-points)
12. [Tech Stack Reference](#12-tech-stack-reference)
13. [Directory Structure](#13-directory-structure)

---

## 1. Project Overview

**Novaforge** is a game development project managed inside **Arbiter**. It combines:

- A **custom Atlas core + ECS** game engine (C++/C#) targeting Unity, Unreal, and Godot
- **AI-powered procedural content generation** (rooms, interiors, exteriors)
- **Modular mech suit upgrade systems** with tiered visual propagation
- **Server administration** via the standalone SteamServerAdmin project
- **Full AI development agent** integration via ArbiterAI for autonomous iteration

Arbiter acts as the AI development platform — planning, generating code, iterating assets, and overseeing servers autonomously.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Novaforge System                         │
│                                                                 │
│  ┌───────────────────┐    ┌──────────────────────────────────┐  │
│  │   Tooling Layer   │◄──►│       ArbiterAI Manager         │  │
│  │   (WPF App)       │    │  (ArbiterEngine + PythonBridge)  │  │
│  │                   │    │                                  │  │
│  │ • Chat Panel      │    │ • 40-prompt live memory          │  │
│  │ • File Explorer   │    │ • SQLite prompt archive          │  │
│  │ • Status Log      │    │ • Action generation/execution    │  │
│  │ • VS Integration  │    │ • Streaming responses            │  │
│  └────────┬──────────┘    └──────────────┬───────────────────┘  │
│           │                              │                       │
│           ▼                              ▼                       │
│  ┌────────────────┐         ┌───────────────────────┐           │
│  │  Game Systems  │         │  Remote Web Interface  │           │
│  │                │         │  (React/Blazor)        │           │
│  │ • Atlas ECS    │         │                        │           │
│  │ • Mech System  │         │ • /ai/stream (SSE)     │           │
│  │ • PCG Engine   │         │ • /ai/actions          │           │
│  └────────────────┘         │ • /ai/theme            │           │
│                             └───────────────────────┘           │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │         SteamServerAdmin (standalone project)            │   │
│  │  Projects/SteamServerAdmin — REST API + Web Dashboard    │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Tooling Layer

The Tooling Layer is a **WPF application** providing the developer-facing interface for Novaforge.

### 3.1 Panels

| Panel | Purpose |
|---|---|
| **Chat** | Real-time AI chat with streaming token display |
| **File Explorer** | Project file tree, open/edit files |
| **Tooling Layer** | AI action list with one-click execution |
| **Status Log** | Live server status, player count, restart warnings |

### 3.2 Theme System

Three built-in themes plus user-defined custom themes:

| Theme | Background | Panel | AI Text |
|---|---|---|---|
| **Dark (default)** | `#202123` | `#2A2B2F` | `#00FFAB` |
| **Day** | `#F5F5F5` | `#E6E6E6` | `#007864` |
| **Custom** | user-defined | user-defined | user-defined |

Themes are persisted in `settings.json`. The `/ai/theme` API endpoint exposes the active palette for the remote web client.

### 3.3 Visual Studio Integration

The Tooling Layer connects to the **Arbiter VSIX** for:
- Inline AI code suggestions within the VS editor
- Code generation actions dispatched from the Chat panel
- Diagnostic overlays driven by ArbiterAI analysis

---

## 4. AI Integration (ArbiterAI)

### 4.1 ArbiterAI Manager

A **singleton** (`ArbiterAIManager`) manages:
- **40-prompt live memory** window (last 40 user/AI turns in RAM)
- Older prompts archived to **SQLite** (`ai_archive.db`) with tag-based retrieval
- `RetrieveRelevantArchives(query)` injects past context back into new prompts
- **Workspace context** — tracks all project files, tooling state, server state

### 4.2 Action System

```
GenerateActionsAsync(prompt) → List<AIAction>
ExecuteActionAsync(action)   → Result
```

**Action types:**
- `insert_prefab` — place a PCG prefab into the scene
- `add_script` — generate and add a C# script
- `tooling_update` — update tooling state or configuration
- `server_command` — relay an RCON command to SteamServerAdmin

### 4.3 Streaming

AI responses stream token-by-token via `IAsyncEnumerable<string>`. The Chat panel renders tokens in real time. The remote web client receives the same stream via the SSE endpoint `/ai/stream`.

### 4.4 Open-Source Models

Novaforge supports **Ollama** and **CodeGeeX** as local LLM backends for unrestricted free code assistance.

---

## 5. Game Systems — Atlas Core + ECS

### 5.1 Architecture

Novaforge uses a **custom Entity-Component-System** built on the Atlas core:

```
World
 ├── EntityManager     — create/destroy entities; assign components
 ├── ComponentStore    — sparse-set storage per component type
 ├── SystemScheduler   — ordered system execution each frame
 └── EventBus          — decoupled cross-system messaging
```

### 5.2 Core Entities

| Entity | Components |
|---|---|
| **Mech** | Transform, Reactor, Armor, Weapons, Cockpit, PCGTier |
| **Room** | Transform, RoomLayout, InteriorStyle, PCGComplexity |
| **Actor** | Transform, Stats, AI, RenderMesh |

### 5.3 Target Platforms

The Atlas ECS is engine-agnostic. Adapters are planned for:
- **Unity** — MonoBehaviour bridge + ECS interop
- **Unreal** — Actor component bridge
- **Godot** — Node bridge

---

## 6. Mech Suit Upgrade System

### 6.1 Tier Model

Every mech system has **5 upgrade tiers** (T1–T5). Tier is set on the `Reactor` (the power source) and cascades to all other systems.

```
Reactor Tier → unlocks higher Armor / Weapons / Cockpit tiers
```

### 6.2 Systems

| System | Tier Effects |
|---|---|
| **Reactor** | Power output; gates all other upgrades |
| **Armor** | Damage resistance; visual — plate density, conduit colours |
| **Weapons** | Hardpoint count; visual — weapon mount geometry, LCD overlays |
| **Cockpit** | Interior aesthetics — LCD panels, pipe layouts, lighting density |

### 6.3 Visual Propagation

Upgrading any system triggers a **PCGTier event** on the mech entity:
1. `InteriorStyleSystem` re-generates cockpit interior assets
2. `ExteriorStyleSystem` re-generates exterior plating and mounts
3. PCG engine re-evaluates room/base complexity for the new tier

### 6.4 Piloted Mechanic

- Player entry/exit via interaction trigger
- Cockpit camera replaces third-person camera
- HUD panels (health, ammo, reactor, map) rendered on in-world LCD meshes
- Control bindings forwarded through `CockpitInputSystem`

---

## 7. Procedural Content Generation (PCG)

### 7.1 Generation Targets

| Target | Description |
|---|---|
| **Rooms / Interiors** | Modular tile-based room layout + prop placement |
| **Mech Cockpit** | Dynamic panel/pipe/conduit layout driven by tier |
| **Base Exteriors** | Building façades and weapon mounts react to mech tier |

### 7.2 Complexity Scale

PCG complexity is a continuous value `[0.0, 1.0]` derived from the mech's `PCGTier` component:

```
T1 → 0.0–0.2  (minimal, raw)
T2 → 0.2–0.4
T3 → 0.4–0.6  (standard)
T4 → 0.6–0.8
T5 → 0.8–1.0  (elite, dense)
```

### 7.3 Asset Pipeline

```
PCGRequest(type, complexity, seed)
  → ModuleSelector     — pick compatible asset modules for tier
  → LayoutSolver       — spatial placement using constraint rules
  → PropPlacer         — secondary detail placement (pipes, panels, decals)
  → PrefabInstantiator — spawn GameObjects / scene nodes
```

### 7.4 AI-Assisted Iteration

ArbiterAI can:
- Generate new PCG modules (prefab + script) on demand from a text description
- Validate that all generated assets remain consistent with the current tier after any change
- Archive all generated assets in the SQLite prompt archive for cross-project reuse

---

## 8. Server Administration (SteamServerAdmin)

Server management for Novaforge game servers is handled by the **standalone SteamServerAdmin project** at `Projects/SteamServerAdmin`. Novaforge integrates with it at runtime via the SSA REST API.

### 8.1 Integration Points (Phase 3)

| Task | Description |
|---|---|
| NF3-1 | Wire Novaforge app IDs and install paths into SSA config |
| NF3-2 | Surface SSA status events (uptime, player count, restart warnings) in Tooling Layer |
| NF3-3 | Feed Novaforge server logs into SSA AI monitoring thresholds |
| NF3-4 | Supply Novaforge-specific roles/whitelist to SSA permission system |
| NF3-5 | End-to-end integration test |

See `Projects/SteamServerAdmin/roadmap.json` for the full SSA implementation plan.

---

## 9. Remote Web Interface

Novaforge exposes a persistent local web server so the project can be accessed from any browser or device.

### 9.1 API Endpoints

| Endpoint | Description |
|---|---|
| `GET /ai/query` | Single-turn AI query |
| `GET /ai/stream` | SSE token stream |
| `POST /ai/actions` | Generate AI action list |
| `POST /ai/execute` | Execute an AI action |
| `GET /ai/workspace` | Current workspace context snapshot |
| `GET /ai/theme` | Active colour palette JSON |

### 9.2 Authentication

Token-based auth (API key per user). Destructive actions (server restart, code generation) require elevated role.

---

## 10. AI Development Agent

ArbiterAI operates as a **full-time autonomous development agent** for Novaforge in Phase 5:

| Capability | Description |
|---|---|
| **Repo monitoring** | Watches for new commits; proposes or implements follow-up changes |
| **PCG coherence** | Validates assets stay consistent with mech tiers after every change |
| **Dev loop** | Code generation → test → asset placement → AI feedback → iteration |
| **Server automation** | Triggers SSA scripts from log thresholds without manual input |
| **Prefab learning** | Archives all generated assets tagged by feature type for reuse |
| **Undo / versioning** | Tracks all AI-generated changes; any single action revertible |
| **Conflict detection** | Detects collisions with existing project logic; pauses for review |

---

## 11. Integration Points

### Novaforge ↔ ArbiterAI

- `ArbiterAIManager` singleton initialized at Tooling Layer startup
- Context injected: workspace files, tooling state, server state, mech tier
- Actions generated and executed through the Tooling Layer

### Novaforge ↔ Visual Studio

- Arbiter VSIX connects to Tooling Layer via named pipe / local HTTP
- Inline suggestions rendered as VS editor adornments
- Code-generation actions dispatched from VS command palette

### Novaforge ↔ SteamServerAdmin

- SSA REST API at `http://localhost:<ssa_port>/`
- Status events polled on 30s interval and displayed in the Status Log panel
- RCON commands relayed via `AIAction` of type `server_command`

---

## 12. Tech Stack Reference

| Layer | Technology |
|---|---|
| Game Engine | Custom Atlas core + ECS (C++/C#) |
| Tooling Layer | WPF (.NET 8), WebView2 (Monaco IDE embed) |
| AI Backend | ArbiterEngine (FastAPI, Python 3.11+) |
| Bridge | PythonBridge (FastAPI, port 8000) |
| LLM Backends | Ollama, CodeGeeX (local/offline) |
| Prompt Archive | SQLite (`ai_archive.db`) |
| Remote UI | React or Blazor (dark mode, ChatGPT palette) |
| Server Admin | SteamServerAdmin (FastAPI REST + React dashboard) |
| CI/CD | GitHub Actions (VSIX build, Docker push) |

---

## 13. Directory Structure

```
Projects/Novaforge/
├── roadmap.json               ← Arbiter project tracking
├── docs/
│   └── design/
│       └── MASTER_DESIGN_BIBLE.md   ← this document
├── Core/
│   └── ECS/                   ← Atlas core + ECS stubs (NF0-3)
├── ToolingLayer/              ← WPF panel stubs (NF0-4)
├── GameSystems/
│   ├── Mech/                  ← Mech upgrade system stubs (NF0-5)
│   └── PCG/                   ← Procedural generation stubs (NF0-5)
├── ServerAdmin/               ← SSA integration stubs (NF0-6)
└── AI/                        ← ArbiterAI automation stubs (NF0-7)
```
