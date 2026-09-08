# Open2D Cortex — Agent Architecture

## Target topology

```text
                         +----------------------+
                         |      User / Chat     |
                         +-----------+----------+
                                     |
                                     v
+-------------------+       +--------+---------+       +--------------------+
| Open2D Foundry UI |<----->|  Open2D Cortex   |<----->| VS Code Extension  |
+-------------------+ RPC   | service / agent  | RPC   +--------------------+
         |                  +---+-----+----+----+
         |                      |     |    |
         |                      |     |    +----------+
         |                      |     |               |
         v                      v     v               v
+-------------------+     +--------+ +-----------+ +------------------+
| Ember Runtime     |     | Tools  | | Memory    | | Model Providers  |
| RuntimeBridge     |     | Broker | | / RAG     | | LM Studio first  |
+-------------------+     +---+----+ +-----------+ +------------------+
                              |
                 +------------+-------------------------+
                 |            |           |             |
                 v            v           v             v
              Source       Build/Test   Process      Capture/Vision
              edits        diagnostics  launch       inspection
```

## Core principle

The model **does not own the machine**. Cortex owns capabilities; the model requests them.

Every tool request is checked against:

- current workspace;
- current agent mode;
- allowed paths;
- allowed commands;
- process ownership;
- transaction state;
- user approval policy.

## Session model

`AgentSession` should track:

- session ID;
- project ID/root;
- selected provider/model routes;
- conversation state;
- tool iteration count;
- transaction/checkpoint ID;
- active Foundry/Ember processes;
- VS Code connection;
- runtime connection;
- screenshots/evidence;
- diagnostics;
- changed files.

## Provider interface

Conceptually:

```rust
trait ModelProvider {
    async fn list_models(&self) -> Result<Vec<ModelInfo>>;
    async fn respond(&self, request: AgentModelRequest) -> Result<AgentModelResponse>;
    fn capabilities(&self) -> ProviderCapabilities;
}
```

Capabilities include:

- tool calling;
- image input;
- embeddings;
- stateful response continuation;
- reasoning controls;
- MCP support.

Do not assume every model route has every capability.

## LM Studio mapping

Prefer:

- `POST /v1/responses` — main Cortex agent loop;
- `POST /v1/chat/completions` — compatibility fallback;
- `/api/v1/models*` — optional model lifecycle/management;
- LM Studio MCP integration only where it adds value.

Cortex's own Open2D tools should remain native structured tools. Do not force core project editing through third-party MCP servers.

## RPC layer

Recommended first implementation:

- loopback-only HTTP/WebSocket;
- random per-session bearer token;
- connection record stored under `.open2d/session/`;
- no LAN bind by default.

Clients:

- Foundry;
- VS Code extension;
- Ember Runtime;
- CLI.

Message families:

- `session.*`
- `workspace.*`
- `source.*`
- `build.*`
- `runtime.*`
- `capture.*`
- `diagnostics.*`
- `memory.*`
- `approval.*`

## Transaction model

Before the first mutation in an agent turn:

```text
CreateCheckpoint
    -> collect affected-file hashes
    -> apply edits
    -> format
    -> verify
    -> accept or rollback
```

A transaction records:

- base hashes;
- proposed patches;
- applied edits;
- generated files;
- commands run;
- diagnostics;
- screenshots;
- final hashes.

Rollback must work without Git. If Git exists, Git status/diff can supplement but should not be the only safety system.

## Permission modes

### Observe
Read/search/status/diagnostics/capture only.

### Guided
May edit/build/run after explicit approval for the transaction.

### Workspace Autonomy
May edit/build/test/launch within the active Open2D workspace using approved tool classes, but cannot:

- escape workspace roots;
- install arbitrary software;
- modify global system settings;
- access unrelated personal folders;
- bind externally;
- run destructive shell commands outside the tool policy.

This is the closest mode to "work on the project like we do here" while keeping operations bounded.

## Why VS Code is a bridge, not the brain

VS Code gives Cortex an excellent coding surface:

- user-visible diffs;
- active selections/context;
- workspace edits;
- diagnostics;
- terminal/tasks;
- file navigation.

But the agent session must live in Cortex so the same AI can also:

- manipulate Open2D resources in Foundry;
- launch Ember;
- inspect game state;
- capture screenshots;
- use project memory;
- operate headlessly.

That makes VS Code optional but deeply integrated.
