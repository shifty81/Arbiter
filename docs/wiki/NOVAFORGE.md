# Novaforge

> **Type:** Game Development Project  
> **Managed by:** Arbiter  
> **Project file:** [`Projects/Novaforge/roadmap.json`](../../Projects/Novaforge/roadmap.json)  
> **Related project:** [SteamServerAdmin](STEAM_SERVER_ADMIN.md) — handles all server administration

---

## Overview

Novaforge is a game development project that runs entirely inside Arbiter as a managed workspace. Arbiter acts as its AI development platform — planning features, generating code, iterating assets via the self-build loop, and bridging into Visual Studio for inline suggestions.

The project is centred on three interconnected systems:

1. **Atlas Core + ECS** — a custom entity-component-system game engine foundation
2. **Mech Suit Systems** — modular, tiered upgrades with full visual propagation
3. **Procedural Content Generation (PCG)** — AI-assisted room, interior, and exterior generation

All server administration for Novaforge's live game servers is delegated to the **SteamServerAdmin** standalone project. The two projects integrate at runtime; Novaforge supplies its server identifiers and configs while SteamServerAdmin handles all operations.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         ARBITER PLATFORM                        │
│                                                                 │
│  ┌──────────────────┐    ┌─────────────────────────────────┐   │
│  │  Chat Engine     │    │  Visual Studio Extension (VSIX) │   │
│  │  (ArbiterEngine) │    │  Inline AI for Novaforge code   │   │
│  └────────┬─────────┘    └────────────────┬────────────────┘   │
│           │                               │                     │
│           ▼                               ▼                     │
│  ┌────────────────────────────────────────────────────────┐    │
│  │             Arbiter Tooling Layer (WPF)                │    │
│  │  ┌──────────┐ ┌──────────────┐ ┌──────────────────┐  │    │
│  │  │ Chat     │ │ File Explorer│ │ Tooling / Prefabs│  │    │
│  │  │ Panel    │ │ Panel        │ │ Panel            │  │    │
│  │  └──────────┘ └──────────────┘ └──────────────────┘  │    │
│  │  ┌──────────────────────────────────────────────────┐  │    │
│  │  │          Status / Logs Panel                     │  │    │
│  │  └──────────────────────────────────────────────────┘  │    │
│  └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
          │                               │
          ▼                               ▼
┌─────────────────┐           ┌───────────────────────┐
│ NOVAFORGE       │           │ SteamServerAdmin       │
│                 │  REST API │ (standalone project    │
│ Atlas Core+ECS  │◄─────────►│  — accessed via HTTP,  │
│ Mech Suit Sys.  │  + events │  not imported directly)│
│ PCG Engine      │           │ start/stop/restart     │
│ Game Assets     │           │ role permissions       │
└─────────────────┘           │ AI health monitoring   │
                              │ web dashboard          │
                              └───────────────────────┘
```

---

## Game Systems

### Atlas Core + ECS

The foundation of Novaforge's runtime. A custom entity-component-system architecture that defines all game entities, their components, and the systems that process them.

| Entity    | Key Components                              |
|-----------|---------------------------------------------|
| Mech      | ReactorComponent, ArmorComponent, WeaponsComponent, CockpitComponent |
| Room      | PCGLayoutComponent, TierComponent, AssetListComponent |
| Actor     | TransformComponent, PhysicsComponent, InputComponent |

**Integration:** ECS drives both mech upgrades and PCG — the tier level of a Mech entity directly informs the complexity of PCG-generated rooms and asset sets.

---

### Mech Suit Systems

Piloted mech suits with modular, tiered upgrade paths. Each subsystem is independent but visually and functionally linked through the ECS.

#### Upgrade Tiers

| Subsystem | What Upgrades                        | Visual Propagation                          |
|-----------|--------------------------------------|---------------------------------------------|
| Reactor   | Power output tier (1–5)              | Conduit density, glow effects in cockpit    |
| Armor     | Plating durability and coverage      | Exterior plating textures, damage overlays  |
| Weapons   | Hardpoint count and weapon class     | Exterior mounts, LCD targeting overlays     |
| Cockpit   | Interface tier, pilot comfort        | Interior layout, LCD panels, pipe routing   |

#### Visual Propagation Rules

```
Tier change → ECS TierComponent updated
            → PCGLayoutComponent recalculated
            → AssetListComponent refreshed with tier-appropriate prefabs
            → All visual meshes/materials swapped via asset swap system
```

#### Piloted Mechanic

- Player enters via interaction trigger → cockpit camera activates
- HUD panels populated from CockpitComponent (health bars, weapon status, reactor output)
- All controls routed through MechInputSystem (separate from standard player controls)
- Exit returns control to standard player input

---

### Procedural Content Generation (PCG)

AI-assisted generation of rooms, interiors, and exteriors. Generation complexity scales with the active mech tier.

#### Room Generation Pipeline

```
1. Seed input (mech tier, biome, room type)
2. Layout generation — floor plan using tile-based or BSP algorithm
3. Asset selection — pull tier-appropriate prefabs from Assets/PCG/
4. Placement — modular dynamic asset placement engine
5. Decoration — pipe/conduit/LCD panel overlays driven by mech upgrade state
6. Finalise — connectivity check, exit/entry point validation
```

#### PCG ↔ Mech Integration

- Reactor tier → power conduit density and glow intensity in generated rooms
- Armor tier → wall material selection and damage decal frequency
- Weapons tier → weapon rack, ammo storage, and targeting display assets
- Cockpit tier → LCD panel count, control interface layout, pilot access panel

#### ArbiterAI PCG Assistance

ArbiterAI can generate new PCG prefabs and scripts on demand through the Tooling Layer:

```
User: "Generate a Tier 3 mech reactor room with high conduit density"
→ AI queries prefab archive for Tier3, Reactor, Room tags
→ AI generates new prefab file at Assets/PCG/Reactor/T3_HighConduit.prefab
→ AI generates placement script at Scripts/Mech/PCG/T3ReactorRoomPlacer.cs
→ Both are clickable actions in the chat panel — insert with one click
```

---

## Tooling Layer (WPF)

The Novaforge Tooling Layer is a WPF application wired into Arbiter. It is the primary developer interface for the project.

### Panel Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ File Explorer (250px) │ AI Chat / Project Workspace (*)         │ Tooling (300px) │
│                       │                                         │                 │
│  Project tree         │  Streaming AI responses                 │  Prefab editor  │
│  Click → AI context   │  Clickable action buttons               │  Script scaffold│
│                       │  User prompt input                      │  Asset generator│
├───────────────────────┴─────────────────────────────────────────┴─────────────────┤
│ Status / Logs Panel (150px — full width)                                          │
│ Server status · Build output · AI reasoning · Audit events                        │
└───────────────────────────────────────────────────────────────────────────────────┘
```

### GUI Theme System

| Theme  | Background | Panel    | AI Text  | User Text |
|--------|------------|----------|----------|-----------|
| Dark   | `#202123`  | `#2A2B2F`| `#00FFAB`| `#FFFFFF` |
| Day    | `#F5F5F5`  | `#E6E6E6`| `#007864`| `#000000` |
| Custom | user-defined RGB | | | |

Dark mode is the default. Themes apply dynamically at runtime via `GUIThemeManager.OnThemeChanged` — all panels, inputs, buttons, and the remote browser client update simultaneously without restart.

---

## AI Integration

### ArbiterAI Manager

The AI singleton (`ArbiterAIManager`) is always running inside Arbiter and is fully workspace-aware:

- **Live memory:** last 40 prompts in RAM
- **Archive:** prompts older than 40 persisted to SQLite with tags (`Mech`, `PCG`, `Template`, `Prefab`, etc.)
- **Workspace snapshot:** AI always knows current file state, tooling state, and server state
- **Streaming:** `IAsyncEnumerable<string>` token stream to chat panel and remote web UI

### Example Interactions

```
"Add a tier 4 cockpit upgrade that includes a holographic targeting overlay"
→ AI generates: Scripts/Mech/CockpitT4HoloTargeting.cs
→ AI generates: Assets/Prefabs/Mech/CockpitT4_HoloOverlay.prefab
→ AI updates: ECS CockpitComponent to add HoloTargetingModule
→ Clickable actions appear in chat to apply all three with one click

"What tier of mech weapons can a Tier 2 Reactor support?"
→ AI reads workspace (ReactorComponent.cs) and responds with constraint table

"Generate a mech hangar room that fits a Tier 3 mech"
→ AI queries prefab archive for Hangar, T3 tags
→ AI generates new PCG room layout and asset placement script
```

### Prompt Archive & Learning

All prompts and AI responses are tagged and archived. The archive feeds back into every new query:

| Tag examples      | What gets retrieved                                 |
|-------------------|-----------------------------------------------------|
| `Mech, Cockpit`   | Past cockpit designs, code patterns, prefab layouts |
| `PCG, Room, T3`   | Previous Tier 3 room generation examples            |
| `Template`        | Starter templates usable for new subsystems         |

---

## Remote Web UI

Novaforge's Tooling Layer exposes the same AI chat and action interface via a local web server for remote brainstorming and planning:

| Endpoint              | Purpose                                      |
|-----------------------|----------------------------------------------|
| `GET /ai/stream`      | SSE token stream — live AI typing in browser |
| `POST /ai/actions`    | Get clickable action suggestions from AI     |
| `POST /ai/execute`    | Execute an AI action (prefab, script, etc.)  |
| `GET /ai/workspace`   | Current workspace snapshot as JSON           |
| `GET /ai/theme`       | Current theme palette as JSON                |

Access via LAN IP or ngrok tunnel. Optional token-based authentication for destructive actions.

---

## Development Roadmap Summary

| Phase | Name                             | Status    | Tasks |
|-------|----------------------------------|-----------|-------|
| 0     | Repo Organisation & Setup        | 🔄 Active | 8     |
| 1     | Tooling Layer & AI Integration   | ⏳ Pending| 13    |
| 2     | Remote Web Interface             | ⏳ Pending| 8     |
| 3     | SteamServerAdmin Integration     | ⏳ Pending| 5     |
| 4     | Game Systems & PCG               | ⏳ Pending| 10    |
| 5     | Development Agent Integration    | ⏳ Pending| 7     |
| 6     | Integration & Testing            | ⏳ Pending| 5     |
| 7     | Deployment & Scaling             | ⏳ Pending| 5     |

Full task breakdown: [`Projects/Novaforge/roadmap.json`](../../Projects/Novaforge/roadmap.json)

---

## Directory Structure

```
Projects/Novaforge/
├── roadmap.json              # Arbiter project profile + full task roadmap
├── src/                      # (pending) source code root
├── docs/                     # (pending) project-level documentation
├── Assets/
│   ├── Prefabs/Mech/         # Mech prefab assets (cockpit, armor, weapons, reactor)
│   └── PCG/                  # PCG asset library (rooms, interiors, exteriors)
├── Scripts/
│   ├── Mech/                 # Mech system scripts (ECS components + systems)
│   └── Server/               # Server integration hooks (→ SteamServerAdmin)
└── Core/
    └── ECS/                  # Atlas core + ECS foundation
```

---

## Related Documentation

- [Architecture Overview](ARCHITECTURE.md)
- [SteamServerAdmin](STEAM_SERVER_ADMIN.md) — standalone server management project
- [Chat Engine](CHAT_ENGINE.md) — how Arbiter AI powers Novaforge development
- [Self-Build](SELF_BUILD.md) — autonomous AI-driven development loop
- [API Reference](API_REFERENCE.md) — all Arbiter API endpoints available to Novaforge
