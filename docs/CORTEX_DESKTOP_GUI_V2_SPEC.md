# Cortex Desktop GUI v2 Normalization Specification

## Principle

The GUI is a first-class client of Cortex authorities. It does not secretly implement alternate project operations, Git logic, provider lifecycles or plugin behavior.

## Application shell

### Left rail — Projects and conversations
- Projects/workspaces as top-level expandable rows.
- Chats nested directly under each project.
- Pinned/global assistant conversations separate from project chats.
- Health/activity badges on project rows.
- Right-click context actions generated from command registry/plugin contributions.

### Center — Conversation / Work / Project Home
Three closely related surfaces:

1. **Chat**
   - streaming response cards;
   - code/file diff cards;
   - tool-call cards;
   - approvals;
   - artifacts;
   - execution evidence.

2. **Work**
   - active milestone/task;
   - plan and acceptance criteria;
   - live job graph;
   - source transactions/diffs;
   - terminal/process streams;
   - test/build/certification evidence;
   - rollback/retry.

3. **Project Home**
   - README/overview;
   - canonical roadmap/milestones;
   - PCC health/last gate;
   - Git/Forgejo state;
   - recent activity;
   - artifacts/builds/debug bundles;
   - integrations/plugins;
   - project memory/index status.

### Right contextual panel
Collapsible tabs:
- Context
- Files
- Diff/Review
- Tasks
- Tools
- Integrations
- Model/Provider
- Inspector

It must remain contextual and not become a permanent wall of debug controls.

## Universal PCC integration

Add a Project Operations surface backed **only** by the PCC client adapter.

Show:
- project health;
- available commands;
- current/last quality gate;
- patch inbox status;
- build/test/run actions;
- logs;
- artifacts;
- rollback/recovery;
- source-control state.

GUI buttons call PCC commands. They do not spawn project-specific commands themselves.

## Source Control / Forgejo

Unify:
- Git working tree;
- branches/commits;
- internal recovery checkpoints;
- optional GitHub remote;
- Forgejo repositories/issues/PRs/releases.

Forgejo is a provider/integration, not a hard dependency for local project operation.

## Plugin Center

Required views:
- Installed
- Available/discovered
- Project integrations
- Permissions
- Health
- Updates
- Developer

Each plugin card shows:
- version;
- protocol version;
- origin;
- permissions;
- capabilities;
- projects using it;
- last health result;
- update compatibility.

## Tool Explorer

A searchable live view of the tool catalog:
- origin;
- schema;
- permission class;
- availability;
- project applicability;
- last execution;
- test-call button.

This replaces opaque "106 tools" as the only operational evidence.

## Jobs and execution

Every long operation must be a visible durable job.

Status model:
- queued
- preparing
- running
- awaiting approval
- cancelling
- cancelled
- succeeded
- failed
- interrupted
- degraded

Stop is bound to the typed cancellation authority. The UI displays whether a stop was cooperative, hard-interrupted, or only discarded an external provider result.

## Provider/model surface

Separate:
- provider process/service;
- installed/available models;
- role routing (chat/tool/vision/embedding);
- VRAM/resource leases;
- health;
- active request;
- request queue.

No hidden auto-replay of failed user requests.

## Library / Storage

Keep this as a first-class Cortex workspace:
- Overview
- Browse
- Projects
- Assets
- Code
- Models
- History
- Storage
- Review Queue
- Collections
- Search

The Library catalogs and proposes organization. Destructive moves remain transactional/reviewable.

## IDE/code surface

Cortex should have a native workbench path for:
- syntax-highlighted source view;
- search;
- references;
- diffs;
- terminal;
- build/test output;
- diagnostics.

Use LSP/DAP where appropriate rather than inventing language semantics.

## Ember / Havenwild / Open2D integration UX

Every connected application gets an Integration card with:
- connection state;
- protocol/capabilities;
- active project;
- editor/runtime session state;
- exposed tools/resources;
- permissions;
- logs;
- open/focus action.

Cortex should be able to request:
- open asset/file/editor surface;
- query selected resource;
- apply reviewed asset/code transaction;
- launch PIE/test workflow through the project's adapter/PCC;
- receive runtime/editor events.

It should not reach into editor memory through undocumented hooks.

## UI test strategy

Replace screenshot/string-marker acceptance as the primary authority with:
- controller state-machine tests;
- command routing tests;
- layout snapshot tests for stable structural surfaces;
- accessibility/focus tests;
- cancellation behavior tests;
- plugin contribution tests;
- project switching isolation tests;
- long-job non-blocking tests.
