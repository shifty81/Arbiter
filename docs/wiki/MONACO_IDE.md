# Monaco IDE

Arbiter's built-in web IDE is available at `http://127.0.0.1:8000/gui/`
(or port 8001 for the Engine). It provides a VS Code-like experience with
40+ tool panels organised into logical groups.

---

## Accessing the IDE

| Method | URL |
|--------|-----|
| Via WPF app | Launch the IDE window from the WPF launcher |
| Via browser | `http://127.0.0.1:8000/gui/` (PythonBridge) or `http://127.0.0.1:8001/gui/` (Engine) |
| Via Docker | `http://localhost:8001/gui/` |

---

## Layout

The IDE uses a VS Code-style layout:

- **Activity bar** (left strip) — icon buttons for the most-used panels (Explorer, Search, Git,
  AI Backends, Code Tools, CI/CD, Monitoring, Analytics, Notes, Settings).
- **⋮ More** button at the bottom of the activity bar opens the **overflow panel picker**, which
  lists every remaining panel organised into 7 named groups.
- **Sidebar** — the content panel that changes when you click an activity-bar icon or pick from
  the overflow menu.
- **Editor area** — one or two Monaco editor panes (split view via the ⫿ button).
- **Chat panel** — resizable AI chat on the right side.
- **Output panel** — build/test/agent output at the bottom.

---

## IDE Panels

### Activity Bar (always-visible icons)

| Panel | Description |
|-------|-------------|
| **Explorer** | File tree for the active project; create, rename, delete files |
| **File Search** | Fuzzy search across all project files |
| **Source Control (Git)** | Stage, commit, diff, log, branch — full git workflow |
| **AI Backends** | Switch between LLM backends; view loaded models |
| **Code Tools / Scaffold** | Generate modules, plugins, and test boilerplate with AI |
| **CI/CD** | Trigger CI runs; view history; manage deployment configs |
| **Monitoring** | System resource usage (CPU, RAM, GPU, disk) |
| **Analytics** | Chat usage, response times, AI timeline |
| **Notes** | Per-project free-form notes and tasks |
| **Settings** | App-level settings, config profiles |

---

### AI & Agents _(overflow menu)_

| Panel | Description |
|-------|-------------|
| **Multi-Agent** | View active agents, their tasks and live status |
| **Self-Build Loop** | Start/stop/monitor the autonomous self-build loop |
| **Brainstorm** | AI-powered ideation sessions; export to project |
| **Web Search** | Search the web via DuckDuckGo / SearXNG and inject results into chat |

---

### Code Tools _(overflow menu)_

| Panel | Description |
|-------|-------------|
| **Refactor** | Regex find-replace and symbol rename across the project |
| **Code Quality** | Lint, format, complexity, duplicate detection |
| **Test Runner** | Run tests (pytest / jest / cargo / go); view pass/fail reports |
| **Dep Analyzer** | Dependency graph and security vulnerability scan |
| **Doc Generator** | AI-generated docstrings, READMEs, inline comments |
| **Snippets** | Manage and insert saved code snippets |
| **Diff & Patch** | Compute diffs; apply unified-diff patches |
| **Templates** | Apply project templates; detect toolchain; run code snippets |
| **Utilities** | Archive (pack/extract), docs, package manager, image, audio, debug |

---

### Project _(overflow menu)_

| Panel | Description |
|-------|-------------|
| **Roadmap** | Visual roadmap viewer; mark tasks done, add new tasks |
| **Knowledge** | Browse the knowledge archive; add/remove entries |
| **Library & Archive** | Manage library paths; search the codex |

---

### DevOps _(overflow menu)_

| Panel | Description |
|-------|-------------|
| **Docker** | List containers; build and run images |
| **Deploy** | Manage remote deployment targets and release pipelines |
| **API Client** | HTTP request builder with saved collections |
| **Database** | Browse and query connected databases |
| **Terminal** | Full PTY terminal via xterm.js and `/ws/pty` |

---

### Operations _(overflow menu)_

| Panel | Description |
|-------|-------------|
| **Health Dashboard** | Server health, model status, uptime |
| **Task Queue** | View and manage background shell tasks |
| **Audit Log** | Full JSONL log viewer with level/source filtering |
| **Event Bus** | Inspect live pub/sub events |
| **Cron** | Register and manage recurring scheduled tasks |

---

### Config & Security _(overflow menu)_

| Panel | Description |
|-------|-------------|
| **Env Vars** | View/edit `.env` values (masked secrets) |
| **Vault** | Encrypted secret storage |
| **Webhooks** | Configure inbound/outbound webhooks |
| **Rate Limits** | Configure per-endpoint rate limiting |
| **Feature Flags** | Enable/disable experimental features |
| **Notifications** | Configure desktop/webhook alert rules |

---

### Runtime _(overflow menu)_

| Panel | Description |
|-------|-------------|
| **Model Downloads** | Download GGUF models from HuggingFace; view progress |
| **Plugins** | Browse, install, generate, and manage plugins |

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+B` | Build project |
| `F5` | Run project |
| `Ctrl+T` | Run tests |
| `Ctrl+Shift+P` | Command palette |
| `Ctrl+O` | Open file |
| `Ctrl+S` | Save current file |
| `` Ctrl+` `` | Toggle chat panel |

---

## Customisation

The Monaco editor inherits VS Code settings. You can configure:

- **Theme**: Dark (default), Light, High Contrast
- **Font size**: 12–24px (default 14)
- **Tab size**: 2 or 4 spaces
- **Word wrap**: on/off

Settings are persisted in the browser's `localStorage` so they survive page reloads.
