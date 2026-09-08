# Cortex Repositories + Machine-Local Git + Vault Architecture

Status: locked implementation direction for the Open2D/Cortex project family.

## 1. Product authority split

Cortex owns one project identity. Four first-class workspaces present different
authorities over that same project:

- **Chat** — conversational/agent authority.
- **Workbench** — active editing, search, problems, terminal/build integration.
- **Repositories** — Git history, review, branches, hosted collaboration,
  releases, repository health and remote state.
- **Vault** — large binary payloads, reusable assets, models, archives,
  provenance, content-addressed storage, lineage and storage management.

No workspace maintains a second project database. The Cortex project registry
is the identity spine tying all four together.

## 2. Canonical project graph

A managed project may bind:

- project ID / project family ID;
- working-tree root;
- canonical `.git` working repository;
- machine-local Forgejo repository;
- Vault namespace;
- build/checkpoint authority;
- Cortex conversation history;
- recovery/safety refs;
- optional external mirrors;
- releases and certification evidence.

Forgejo is the default hosted Git service, but the UI and Cortex contracts must
remain provider-neutral.

## 3. Backend choice

### Chosen: Forgejo 15 LTS

Pin the first durable local service to `codeberg.org/forgejo/forgejo:15.0.7`.

Reasons:

- lightweight GitHub-like repository service;
- Issues, pull requests, projects, releases, API, packages and Actions;
- SQLite is appropriate for a personal/low-to-moderate-activity instance;
- local and S3-compatible storage options;
- long-term-support branch is preferable for an embedded personal service;
- Cortex can use Forgejo as a backend without exposing Forgejo's web UI as the
  normal workflow.

### Strongest alternative: OneDev

OneDev has exceptionally integrated code review, CI/CD, issue management,
packages and code navigation. It is an excellent feature/UX reference.
It is not the default backend because those integrated product surfaces
overlap heavily with Cortex Repositories, Activity, Workbench and Vault.

### Other alternatives

- **Gitea** — technically suitable and lightweight; retain as a provider
  possibility.
- **GitLab CE** — capable but materially heavier than necessary for one local
  personal workstation.
- **Soft Serve** — useful lightweight Git/SSH/TUI ideas, but too thin for the
  GitHub-like hosted metadata surfaces Cortex needs.
- **Jujutsu** — borrow operation-log/undo ideas; do not replace Git authority.
- **DVC** — borrow content-addressed payload + Git pointer patterns; do not add
  it as a required dependency.
- **gitoxide/gix** — future fast Rust read/index layer. Keep system Git CLI as
  the mutation authority until gix high-level workflows cover everything
  Cortex needs.

## 4. Machine-local host layout

Default Windows storage:

    D:\Cortex\Git\
      forgejo\
        compose.yaml
        data\
      keys\
        cortex_forgejo_ed25519
        cortex_forgejo_ed25519.pub
        known_hosts

Initial endpoints are loopback-only:

- Web: `http://127.0.0.1:3000/`
- SSH: `ssh://git@127.0.0.1:2222/`

Defaults:

- repositories private;
- push-to-create enabled;
- registration disabled after bootstrap/onboarding;
- SQLite initially;
- existing cloud remotes preserved;
- Cortex local remote defaults to `cortex-local`.

The active project tree is not moved merely because the local host is enabled.
Moving projects to D: is a later transactional Vault migration with dry-run,
reference repair and rollback.

## 5. Git data plane vs hosted metadata plane

### Local Git data plane

System Git remains authoritative for initial mutations:

- init;
- status;
- diff;
- stage/unstage;
- commit/amend;
- branches/tags;
- stash;
- fetch/push;
- merge/rebase/cherry-pick/revert;
- worktrees;
- bundles/recovery.

A future `gix` read layer may accelerate:

- status;
- object/commit graph traversal;
- refs;
- tree/index reads;
- large repository browsing;
- background indexing.

Mutation behavior must stay exact and unsurprising.

### Forgejo management plane

Forgejo REST/API-backed capabilities:

- repositories;
- issues/labels/milestones;
- pull requests/reviews/comments;
- branch protection;
- releases;
- Actions/workflow metadata;
- packages;
- webhooks;
- repository settings.

Never scrape the Forgejo webpage to drive Cortex.

## 6. Authentication

Git transport:

- dedicated Cortex Ed25519 SSH key;
- private key never returned through tool output;
- one-time public-key registration with the local Forgejo account.

Forgejo API:

- scoped repository token initially;
- token stored through Windows Credential Manager/DPAPI-backed secret storage,
  never in Git remote URLs or committed configuration;
- later Authorized Integration/OIDC may replace static tokens for appropriate
  automated jobs.

System/credential operations require the existing strong Cortex permission
authority.

## 7. Vault authority

Git is not the large binary store.

### Git owns

- source code;
- scripts;
- configs;
- docs;
- small project metadata;
- scene/logic/resource descriptors;
- dependency lock files;
- small original assets where appropriate;
- Vault pointer/provenance manifests.

### Vault owns

- large PNG/PSD/KRA source art;
- GLB/FBX/OBJ source assets;
- WAV/FLAC/video;
- GGUF/model files;
- large imported libraries;
- generated binary artifacts;
- source rollups;
- debug bundles;
- build outputs;
- installers/releases;
- backups;
- content-addressed reusable objects.

Default review policy:

- normal source/small files: Git;
- binary/large candidate at 25 MiB: recommend Vault;
- 100 MiB+ payload: require explicit override to store directly in Git;
- policy remains configurable per project/category.

Forgejo LFS remains a compatibility option, not the primary Cortex large-file
authority.

## 8. Vault pointer contract

A Git-tracked Vault reference needs at minimum:

- logical path;
- object/content SHA-256;
- byte size;
- MIME/type;
- Vault namespace/object ID;
- project usage;
- provenance/source URL where applicable;
- license/attribution metadata where applicable;
- modification status/version;
- optional upstream version/checksum.

The release system resolves the exact pointer set before packaging.

## 9. Recovery and Cortex autonomous changes

When a project has real Git, real Git becomes canonical history.
Legacy ShadowGit remains fallback only for projects that have not yet adopted
real Git.

Cortex safety checkpoints must not pollute or rewrite the user's branch.

Reserved namespace:

    refs/cortex/checkpoints/<timestamp-or-operation-id>

A safety checkpoint records/linkages for:

- Git tree/commit;
- Vault manifest snapshot;
- Cortex transaction ID;
- quality-gate result;
- build/runtime evidence;
- optional task/milestone.

Rollback can restore from the safety ref while retaining execution evidence.

Jujutsu's operation-log UX is the inspiration here, but Git remains the actual
repository format.

## 10. Repositories GUI

Primary shell:

    Chat | Workbench | Repositories | Vault

Forgejo's own webpage is an administration/fallback surface only.

### Left repository rail

Groups eventually include:

- Favorites;
- Active;
- Recent;
- Dirty;
- Build Failing;
- Needs Attention;
- Archived;
- Local Only;
- Mirrored.

Nested project families must be representable without pretending every child
folder is an independent Git repository.

### Repository header

Display:

- owner / repository;
- Private/Public;
- branch;
- clean/dirty;
- ahead/behind;
- local-host health;
- build/checkpoint status;
- Vault linked/missing state;
- local-only/mirrored state.

Primary actions:

- Open Workbench;
- Open Vault;
- Ask Cortex;
- Refresh;
- Setup/Manage Git Host.

### Repository navigation

Lock these native sections:

1. **Code**
2. **Changes**
3. **History**
4. **Branches**
5. **Issues**
6. **Pulls**
7. **Actions**
8. **Releases**
9. **Insights**
10. **Settings**

#### Code

Repository-oriented browser:

- branch/tag selector;
- folders/files;
- latest commit per row;
- README/Markdown;
- file preview;
- blame/history/raw;
- repository search;
- Open in Workbench.

It must not become a second IDE.

#### Changes

Borrow the best GitHub Desktop/GitUI behaviors:

- Working Tree / Staged;
- file, hunk and line stage/unstage;
- unified/split diff;
- whitespace toggle;
- discard/revert with confirmation;
- commit subject/body;
- amend;
- stash;
- Ask Cortex to Review.

#### History

- commit graph/list;
- author/time/hash;
- changed files;
- commit/range diff;
- create branch/tag from commit;
- revert/cherry-pick later;
- linked Cortex checkpoint/build evidence.

#### Branches

- local and remote branches;
- current/default/protected;
- ahead/behind;
- create/switch/rename/delete;
- publish/fetch;
- merge/rebase;
- associated worktrees.

#### Issues

Forgejo-backed, native Cortex UI:

- open/closed;
- labels;
- milestones;
- priority;
- assignee;
- comments;
- linked commits/builds/conversations/debug bundles/Vault objects.

#### Pulls

- branch comparison;
- commit/file diff;
- review comments;
- checks;
- approvals;
- merge/squash/rebase controls;
- Ask Cortex to Review.

#### Actions

- Forgejo Actions workflow/run status;
- Cortex build/checkpoint jobs;
- stage summaries.

Live logs remain in bottom **Activity**; Repositories must link/filter Activity
rather than create another log console.

#### Releases

A release binds:

- exact Git commit/tag;
- exact Vault snapshot;
- lock/dependency state;
- build/certification evidence;
- release artifacts/checksums;
- changelog/release notes.

#### Insights

- repository health;
- Git/object size;
- large-file candidates;
- commit activity;
- branch age;
- build/checkpoint pass rates;
- recurring failure categories;
- dependency health;
- Vault usage/references;
- recovery/backup coverage.

#### Settings

- Git identity;
- primary host;
- repository visibility;
- local remote;
- optional cloud mirrors;
- branch protection;
- Actions trust;
- Vault binary threshold;
- safety-checkpoint policy;
- backup policy;
- advanced provider settings.

## 11. GUI responsiveness contract

Repository operations must not repeat the historical Cortex GUI-freeze problem.

Rules:

- no Git process or Forgejo HTTP call on the Win32 UI thread;
- UI reads cached repository snapshots;
- background refresh is incremental/debounced;
- file/history/diff lists are lazy/virtualized for large repos;
- expensive history/blame/search work is cancellable;
- Activity receives job progress;
- repository page remains interactive during jobs.

## 12. Actions security

Forgejo Actions is useful but must not become an arbitrary privileged execution
path.

Initial policy:

- runner disabled until deliberately configured;
- trusted local projects only;
- no automatic execution of workflows imported from untrusted repositories;
- no host Docker socket exposure to arbitrary workflow jobs;
- separate runner workspace/cache;
- Cortex permission/trust policy remains the outer authority;
- build artifacts can be promoted into Vault/Releases only after certification.

## 13. Backups

D:\ Forgejo is the primary local host, not itself the only backup.

Future backup set:

- Forgejo database/config;
- Git repositories or bundles;
- Actions/package metadata where retained;
- Cortex repository registry;
- Vault manifests/index;
- Vault payload backup according to project policy.

Optional cloud remotes are mirrors/backups, never required for normal local
operation.

## 14. Implementation stages

### GIT2 — this handoff

- machine-local Forgejo host foundation;
- Forgejo 15.0.7 LTS pin;
- permission-governed host/key/project tools;
- generic `git.repository.overview`;
- native **Repositories** top-level workspace;
- all ten repository sub-tabs;
- project list and workspace switching;
- Git/status/diff/history snapshot;
- Workbench/Vault/Cortex cross-navigation;
- repository/Vault authority contract and schema.

### GIT3

- provider config/credential store;
- Forgejo REST client;
- real Issues/Pulls/Releases/Actions data;
- repository creation/import/mirror management;
- branch/remote/tag mutation tools.

### GIT4

- rich Changes UI: file/hunk/line staging and split/unified diff;
- commit composer;
- History graph;
- branch/worktree manager;
- hidden Cortex safety refs;
- real-Git replacement of ShadowGit where appropriate.

### GIT5

- Vault pointer manifests;
- automatic large-file review;
- release resolution from Git + Vault;
- D: catalog -> reviewed repository onboarding;
- lineage/duplicate import planning.

### GIT6

- Forgejo Runner/Actions integration;
- hardened workflow trust policy;
- backup/restore;
- optional GitHub/GitLab/Azure/other Forgejo mirrors.

