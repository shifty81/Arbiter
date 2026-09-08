# Cortex Standalone Target Architecture

```text
                         +-----------------------+
                         |    Cortex Desktop     |
                         | chat/projects/jobs/   |
                         | workbench/review      |
                         +-----------+-----------+
                                     |
              +----------------------+----------------------+
              |                      |                      |
              v                      v                      v
       +------+-------+       +------+-------+       +------+-------+
       | Cortex CLI   |       | Cortex Agent |       | API/Clients  |
       | human/headless|      | orchestration|       | IDE/other UI |
       +------+-------+       +------+-------+       +------+-------+
              \______________________|______________________/
                                     |
                         +-----------+-----------+
                         |  Cortex Application   |
                         | Core/Services/Events  |
                         +-----+-----------+-----+
                               |           |
                  +------------+           +----------------+
                  v                                             v
        +---------+----------+                         +--------+---------+
        | Provider/Model/Tool|                         | Plugin/Provider  |
        | Sessions/Context   |                         | Gateway          |
        +--------------------+                         +--------+---------+
                                                               |
                                                               v
                                                    external integrations

                         Cortex Project Operations
                                     |
                                     v
                           +---------+---------+
                           |       FORGE       |
                           | universal project |
                           | development/root  |
                           | operations        |
                           +----+---------+----+
                                |         |
                     +----------+         +------------------+
                     v                                     v
              managed projects                     Git/Forgejo/tools
```

## Cortex owns

- agent/reasoning orchestration;
- conversations/context/memory;
- provider/model routing and lifecycle;
- AI-visible tools and tool routing;
- jobs/tasks/events/activity;
- source-change intent, review and evidence;
- permissions/policy for Cortex actions;
- plugin/tool-provider discovery;
- Desktop/CLI/API application contracts;
- project-aware Library/Vault/index views;
- Cortex's own build/test/release health.

## Forge owns universal project operations

- project discovery/registry/topology;
- universal command registry;
- build/test/run/package orchestration;
- Git/worktrees/execution leases;
- transactional patch/update/apply/rollback;
- filesystem mutation primitives;
- diagnostics/debug bundles/artifacts/history;
- dependency/toolchain resolution;
- project health and machine-readable events;
- source intelligence services shared across managed projects.

Cortex consumes these capabilities rather than implementing a competing operations backend.

## External projects

Open2D/Ember, Havenwild and future projects are ordinary managed projects/integrations. They can expose project-specific capabilities through Forge/project contracts and optional Cortex plugins. Cortex does not need enforcement gates proving their independence.

## Plugin boundary

Prefer out-of-process/versioned contracts for independently upgraded integrations. Internal stable Cortex crates may use native Rust traits. Public integration contracts must describe capabilities, schemas, version compatibility, permissions, cancellation and health.

## State

- Cortex application state: configured Cortex home;
- Cortex Library/Vault/index: configured durable storage;
- Forge machine state: Forge-owned;
- project-local operational state: project/Forge-owned;
- project/editor/runtime state: project-owned;
- secrets: secure user/OS storage, not handoff archives.

Stable IDs and structured contracts connect the systems; migration enforcement does not.
