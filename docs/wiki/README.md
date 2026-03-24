# Arbiter — Documentation Wiki

Welcome to the Arbiter documentation wiki. This documentation is intended to be
mirrored to the in-application Wiki panel and to the GitHub repository wiki pages.

---

## Table of Contents

| Document | Description |
|----------|-------------|
| [Architecture](ARCHITECTURE.md) | System architecture, component map, data flow |
| [Getting Started](GETTING_STARTED.md) | Installation, setup, first run |
| [Configuration](CONFIGURATION.md) | All settings files explained |
| [API Reference](API_REFERENCE.md) | Full REST + WebSocket API documentation |
| [Logging](LOGGING.md) | Logging architecture, log locations, structured logs |
| [Self-Build Loop](SELF_BUILD.md) | Autonomous self-iteration system |
| [VS Extension](VS_EXTENSION.md) | Visual Studio 2022 VSIX extension guide |
| [Chat Engine](CHAT_ENGINE.md) | Chat features, personas, history, voice I/O |
| [Monaco IDE](MONACO_IDE.md) | Built-in web IDE panels and features |
| [Roadmap](ROADMAP.md) | Phase-by-phase project roadmap |
| [Changelog](CHANGELOG.md) | Release history and notable changes |
| [Contributing](CONTRIBUTING.md) | How to contribute, code conventions |
| [Troubleshooting](TROUBLESHOOTING.md) | Common problems and fixes |

---

## Managed Projects

Arbiter manages external projects as first-class workspaces. Each project has its own `roadmap.json` inside `Projects/` and is fully visible in the chat engine, self-build loop, and Tooling Layer.

| Project | Description | Wiki |
|---------|-------------|------|
| [Novaforge](NOVAFORGE.md) | Game project — Atlas Core+ECS, mech suit systems, PCG | [NOVAFORGE.md](NOVAFORGE.md) |
| [SteamServerAdmin](STEAM_SERVER_ADMIN.md) | Standalone autonomous Steam game server administration | [STEAM_SERVER_ADMIN.md](STEAM_SERVER_ADMIN.md) |

---

## Quick Navigation

### For New Users
1. Read [Getting Started](GETTING_STARTED.md) to install and run Arbiter
2. Read [Chat Engine](CHAT_ENGINE.md) to understand chat features
3. Read [Configuration](CONFIGURATION.md) to customize Arbiter

### For Developers
1. Read [Architecture](ARCHITECTURE.md) for the full system picture
2. Read [API Reference](API_REFERENCE.md) to integrate with the backends
3. Read [Self-Build Loop](SELF_BUILD.md) to understand autonomous development
4. Read [Contributing](CONTRIBUTING.md) for code standards

### For VS Users
1. Read [VS Extension](VS_EXTENSION.md) for all VSIX features and shortcuts

---

## About This Documentation

This wiki is auto-generated from source and hand-curated. It is designed to be
rendered both in GitHub Markdown and in Arbiter's built-in Wiki panel (Monaco
web UI). All internal links are relative and work in both environments.

> **Note:** This documentation targets Arbiter v1.1.0. Older versions may differ.
