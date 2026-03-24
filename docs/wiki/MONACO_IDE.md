# Monaco IDE

Arbiter's built-in web IDE is available at `http://127.0.0.1:8000/gui/`
(or port 8001 for the Engine). It provides a VS Code-like experience with
40+ tool panels organised into 9 categories.

---

## Accessing the IDE

| Method | URL |
|--------|-----|
| Via WPF app | Launch the IDE window from the WPF launcher |
| Via browser | `http://127.0.0.1:8000/gui/` (PythonBridge) or `http://127.0.0.1:8001/gui/` (Engine) |
| Via Docker | `http://localhost:8001/gui/` |

---

## IDE Panels

### Navigation

| Panel | Description |
|-------|-------------|
| **Explorer** | File tree for the active project; create, rename, delete files |
| **File Search** | Fuzzy search across all project files |
| **Source Control (Git)** | Stage, commit, diff, log, branch — full git workflow |

---

### AI & Chat

| Panel | Description |
|-------|-------------|
| **AI Chat** | Full chat interface with history, personas, slash commands |
| **AI Backends** | Switch between LLM backends; download new models |
| **Multi-Agent** | View active agents, their tasks and status |
| **Self-Build Loop** | Start/stop/monitor the autonomous self-build loop |
| **Roadmap** | Visual roadmap viewer; mark tasks done, add new tasks |

---

### Code Tools

| Panel | Description |
|-------|-------------|
| **Scaffold** | Generate module/plugin/test boilerplate |
| **Refactor** | Regex find-replace and symbol rename across the project |
| **Brainstorm** | AI-powered ideation sessions |
| **DocGen** | Generate docstrings, READMEs, inline comments |
| **Templates** | Apply conversation or code templates |
| **Snippets** | Manage saved code snippets |
| **Diff & Patch** | Apply unified diffs; preview before applying |

---

### Quality

| Panel | Description |
|-------|-------------|
| **Code Quality** | Lint, complexity, duplicate detection, dependency audit |
| **Test Runner** | Collect and run tests; view pass/fail reports |
| **Dep Analyzer** | Dependency graph and security vulnerability scan |

---

### DevOps

| Panel | Description |
|-------|-------------|
| **CI / Deploy** | Trigger CI runs; view history; manage deployment configs |
| **Docker** | List containers; build and run images |
| **Cron** | Register and manage recurring tasks |
| **Webhooks** | Configure inbound/outbound webhooks |
| **API Client** | HTTP request tester with saved collections |

---

### Project

| Panel | Description |
|-------|-------------|
| **Notes** | Per-project free-form notes |
| **Knowledge** | Browse the knowledge archive; add/remove entries |
| **Library & Archive** | Manage library paths; search the codex |
| **Project Profile** | View project metadata; languages, framework, LLM usage |

---

### Operations

| Panel | Description |
|-------|-------------|
| **Monitoring** | System resource usage (CPU, RAM, GPU, disk) |
| **Insights & Analytics** | Chat usage, response times, persona trends |
| **Task Queue** | View and manage background shell tasks |
| **Audit Log** | Full JSONL log viewer with level/source filtering |
| **Health Dashboard** | Server health, model status, uptime |

---

### Config

| Panel | Description |
|-------|-------------|
| **Env Vars** | View/edit `.env` values (masked secrets) |
| **Vault** | Encrypted secret storage |
| **Feature Flags** | Enable/disable experimental features |
| **Notifications** | Configure desktop/webhook notifications |
| **Settings** | App-level settings (same as `settings.json`) |
| **Rate Limits** | Configure per-endpoint rate limiting |

---

### Runtime

| Panel | Description |
|-------|-------------|
| **Terminal** | Full PTY terminal via xterm.js and `/ws/pty` |
| **Model Downloads** | Download GGUF models from HuggingFace; view progress |
| **Plugins** | Browse, install, and manage plugins |

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
