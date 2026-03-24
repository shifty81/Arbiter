# SteamServerAdmin

> **Type:** Standalone Server Administration Project  
> **Tracked by:** Arbiter (roadmap only — no runtime API coupling)  
> **Project file:** [`Projects/SteamServerAdmin/roadmap.json`](../../Projects/SteamServerAdmin/roadmap.json)  
> **Used by:** [Novaforge](NOVAFORGE.md) and any other game project that needs Steam server management

---

## Overview

SteamServerAdmin is a **fully standalone, autonomous server administration platform**. It lives in the `Projects/` folder so Arbiter can track its roadmap, but it has **no runtime dependency on ArbiterEngine** — it runs independently as its own service with its own API, web dashboard, and AI monitoring.

**Core capabilities:**

- 🔄 Autonomous start / stop / restart / update for any number of Steam game servers
- 🔒 Role-based permissions (Admin, Moderator, Operator, Standard Player)
- 📋 Audit logging of every permission change, ban, kick, and restart
- 🤖 Built-in AI health monitoring — reads live server logs and triggers actions automatically using a local LLM
- 🌐 Full REST API + dark-mode web dashboard for remote administration
- 🔧 Admin script generator — the local AI can write new scripts based on observed failure patterns

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                       SteamServerAdmin                               │
│                                                                      │
│  ┌───────────────┐  ┌───────────────┐  ┌──────────────────────────┐ │
│  │ ServerManager │  │ PermissionMgr │  │ AI Monitor               │ │
│  │ start/stop/   │  │ roles/        │  │ log ingestion pipeline   │ │
│  │ restart/update│  │ whitelist/    │  │ health threshold rules   │ │
│  │ schedules     │  │ audit log     │  │ autonomous action dispatch│ │
│  └───────┬───────┘  └───────────────┘  └──────────────────────────┘ │
│          │                                                           │
│  ┌───────────────┐  ┌──────────────────────────────────────────┐   │
│  │ RCON Client   │  │ FastAPI REST + WebSocket API              │   │
│  │ live server   │  │ /servers, /roles, /audit, /logs          │   │
│  │ commands      │  │ /ws/servers/{id}/logs                    │   │
│  └───────────────┘  └──────────────────────────────────────────┘   │
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │ Local LLM Backend (configurable — Ollama, llama.cpp, etc.)    │  │
│  │ Used by: AI Monitor, admin script generator, AI chat panel    │  │
│  └───────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
            │                             │
            ▼                             ▼
┌──────────────────┐            ┌──────────────────────────────┐
│  SteamCMD        │            │  Web Dashboard (Browser)     │
│  (OS process)    │            │  Dark mode, ChatGPT palette  │
│  install/update/ │            │  Live log stream (WebSocket) │
│  validate        │            │  Role management table       │
│                  │            │  AI chat panel               │
└──────────────────┘            └──────────────────────────────┘
```

> **Note:** SteamServerAdmin is tracked in the Arbiter `Projects/` folder purely for roadmap management. Arbiter's self-build loop can generate code for SSA tasks, but there is no runtime API coupling — SSA runs independently.

---

## Server Registration

Any project registers its servers by adding a config file to `config/`:

```json
{
  "id": "novaforge-main",
  "display_name": "Novaforge Main Server",
  "app_id": 294420,
  "install_path": "C:/Servers/Novaforge",
  "branch": "public",
  "launch_args": "-nographics -batchmode",
  "restart_schedule": "0 4 * * *",
  "update_schedule": "0 3 * * 1",
  "health_rules": [
    { "pattern": "NullReferenceException", "action": "restart", "threshold": 3, "window_minutes": 5 },
    { "pattern": "players: 0", "action": "notify", "threshold": 1, "window_minutes": 60 }
  ],
  "roles": {
    "admin_steam_ids": ["76561198000000001"],
    "moderator_steam_ids": [],
    "operator_steam_ids": []
  }
}
```

---

## Core Operations

### Server Lifecycle

| Command  | What Happens                                                                     |
|----------|----------------------------------------------------------------------------------|
| `start`  | SteamCMD install (if missing) → launch process with `launch_args`               |
| `stop`   | Graceful RCON shutdown → SIGTERM fallback with configurable timeout              |
| `restart`| Broadcast countdown warning → stop → start; configurable warning message/delay  |
| `update` | Broadcast update warning → stop → SteamCMD `+app_update <id> validate` → start |

### Pre-Action Warnings

All restarts and updates can be configured to broadcast a countdown message to connected players before the operation executes:

```json
{
  "restart_warning": {
    "enabled": true,
    "countdown_minutes": 5,
    "message": "Server restarting in {minutes} minutes. Save your progress."
  }
}
```

### Scheduled Operations

Uses cron-style expressions in the per-server config. SteamServerAdmin handles all scheduling internally — no external cron job required.

```
"restart_schedule": "0 4 * * *"    → restart daily at 04:00
"update_schedule":  "0 3 * * 1"    → update every Monday at 03:00
```

---

## Role-Based Permissions

### Permission Tiers

| Role            | Capabilities                                              |
|-----------------|-----------------------------------------------------------|
| **Admin**       | Full control — all operations, role management, whitelist |
| **Moderator**   | Kick, ban, broadcast messages, view audit log             |
| **Operator**    | Restart and update servers; view status and logs          |
| **Standard Player** | Read-only: server status only                         |

### Dynamic Role Changes

Role changes take effect immediately without a server restart. The RCON client and API layer both enforce the new permissions within seconds of a change. All changes are logged to the audit trail.

---

## Audit Log

Every permission change, ban, kick, restart, and update is recorded as a JSONL entry:

```json
{"timestamp":"2026-03-24T04:00:00Z","actor":"admin:76561198000000001","action":"restart","server":"novaforge-main","reason":"scheduled"}
{"timestamp":"2026-03-24T04:01:10Z","actor":"system:ai-monitor","action":"restart","server":"novaforge-main","reason":"NullReferenceException threshold reached (3 in 5 min)"}
{"timestamp":"2026-03-24T14:32:00Z","actor":"moderator:SomePlayer","action":"kick","server":"novaforge-main","target":"76561198000000099","reason":"griefing"}
```

The audit log is:
- Visible in the **Arbiter Tooling Layer** status panel
- Accessible via `GET /servers/{id}/audit` REST endpoint
- Surfaced in the **web dashboard** audit tab
- Queryable via **Arbiter AI chat**: *"What happened on the Novaforge server last night?"*

---

## REST API Reference

Base URL: `http://localhost:8002` (default; configurable)

### Servers

| Method | Endpoint                      | Role Required | Description               |
|--------|-------------------------------|---------------|---------------------------|
| GET    | `/servers`                    | Operator      | List all registered servers |
| GET    | `/servers/{id}/status`        | Operator      | Status, uptime, player count |
| POST   | `/servers/{id}/start`         | Operator      | Start the server          |
| POST   | `/servers/{id}/stop`          | Admin         | Stop the server           |
| POST   | `/servers/{id}/restart`       | Operator      | Restart with warning      |
| POST   | `/servers/{id}/update`        | Operator      | Update via SteamCMD       |
| GET    | `/servers/{id}/logs`          | Operator      | Last N lines of server log |
| WS     | `/ws/servers/{id}/logs`       | Operator      | Live log stream (WebSocket) |

### Permissions

| Method | Endpoint                         | Role Required | Description               |
|--------|----------------------------------|---------------|---------------------------|
| GET    | `/servers/{id}/roles`            | Moderator     | List all role assignments |
| POST   | `/servers/{id}/roles`            | Admin         | Add/update a role         |
| DELETE | `/servers/{id}/roles/{user}`     | Admin         | Remove a role             |
| GET    | `/servers/{id}/whitelist`        | Admin         | Get whitelist             |
| POST   | `/servers/{id}/whitelist`        | Admin         | Add player to whitelist   |
| DELETE | `/servers/{id}/whitelist/{user}` | Admin         | Remove from whitelist     |

### Audit & Config

| Method | Endpoint               | Role Required | Description            |
|--------|------------------------|---------------|------------------------|
| GET    | `/servers/{id}/audit`  | Moderator     | Paginated audit log    |
| GET    | `/api/theme`           | —             | Current Arbiter theme  |
| GET    | `/health`              | —             | SteamServerAdmin health |

### Authentication

All endpoints require an `Authorization: Bearer <api_key>` header. API keys are mapped to roles in `config/auth.json`. Requests with insufficient role are rejected with `403 Forbidden`.

---

## Web Dashboard

The web dashboard is a dark-mode browser UI (ChatGPT colour palette) served at `http://localhost:8002`:

**Panels:**
- **Server List** — status cards for all registered servers (running/stopped, uptime, player count)
- **Per-Server Detail** — live log stream (WebSocket), restart/update/stop buttons gated by role
- **Role Management** — table of all role assignments; Admin can add/remove/promote
- **Audit Log** — paginated, filterable list of all events
- **AI Chat** — embedded Arbiter chat for natural-language queries about server history

**Theme:** Synchronised with Arbiter's current theme via `/api/theme`. Dark mode by default.

---

## AI Health Monitoring

### How It Works

1. SteamServerAdmin tails each registered server's log file in real-time
2. Each new line is checked against the server's `health_rules` array
3. When a rule's `threshold` is reached within its `window_minutes`, the configured `action` fires
4. ArbiterAI is notified; it writes an analysis entry to the Arbiter issues tracker

### Health Rule Actions

| Action     | What Happens                                              |
|------------|-----------------------------------------------------------|
| `restart`  | Trigger `POST /servers/{id}/restart` autonomously        |
| `notify`   | Push alert to Arbiter chat, Tooling Layer, and web dashboard |
| `update`   | Trigger `POST /servers/{id}/update`                      |
| `alert`    | Raise a flagged issue in Arbiter issues tracker           |

### AI Chat Integration

```
"What caused the Novaforge server restart at 4am?"
→ AI queries audit log + log slice around the event
→ AI returns: "3 NullReferenceException entries in 5 minutes triggered the health rule.
   Stack trace points to MechWeaponsSystem.FireHardpoint(). Recommend investigating
   Scripts/Mech/MechWeaponsSystem.cs line ~247."

"Generate a fix for the crash pattern in last night's logs"
→ AI reads the log slice → generates patch suggestion or opens self-build task
```

---

## Logging

SteamServerAdmin writes to the Arbiter top-level log directory:

```
logs/
└── steam_server_admin/
    └── steam_server_admin.log    ← rotating, 5 MB / 5 backups
```

Set up via `setup_system_logging('steam_server_admin')` from `core/logger.py`.

---

## Development Roadmap Summary

| Phase | Name                           | Status     | Tasks |
|-------|--------------------------------|------------|-------|
| 0     | Scaffold & Project Setup       | 🔄 Active  | 5     |
| 1     | Core Server Management         | ⏳ Pending | 8     |
| 2     | Role-Based Permissions & Audit | ⏳ Pending | 7     |
| 3     | REST API & Web Dashboard       | ⏳ Pending | 8     |
| 4     | AI Health Monitoring & Arbiter | ⏳ Pending | 8     |

Full task breakdown: [`Projects/SteamServerAdmin/roadmap.json`](../../Projects/SteamServerAdmin/roadmap.json)

---

## Directory Structure

```
Projects/SteamServerAdmin/
├── roadmap.json        # Arbiter project profile + full task roadmap
├── scripts/            # Admin scripts (start.sh/ps1, stop.sh/ps1, update.sh/ps1)
├── config/             # Per-server JSON configs + auth.json
├── docs/               # Project-level documentation
├── logs/               # Runtime log files (gitignored; populated at runtime)
└── web/                # Web dashboard static assets (index.html, app.js, style.css)
```

---

## Optional Enhancements

- Multi-region server support with a centralised dashboard
- Player analytics: peak hours, average session length, churn tracking
- Discord / webhook notifications for restarts, updates, and permission events
- Backup automation: snapshot server save files before each update
- Mod management: install/update/remove mods via SteamCMD workshop IDs
- Plugin architecture for non-Steam server backends (bare-metal, Pterodactyl)
- AI-generated changelogs from SteamCMD update manifests

---

## Related Documentation

- [Architecture Overview](ARCHITECTURE.md)
- [Novaforge](NOVAFORGE.md) — primary game project that uses SteamServerAdmin
- [Logging](LOGGING.md) — how Arbiter per-system logging works
- [API Reference](API_REFERENCE.md) — full Arbiter API reference
- [Chat Engine](CHAT_ENGINE.md) — how to query SteamServerAdmin events via AI chat
