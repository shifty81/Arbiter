# Configuration

All Arbiter configuration files are documented here. No changes require a
full rebuild — most take effect on the next server start.

---

## HostApp — `HostApp/Config/settings.json`

Controls the WPF desktop application behaviour.

```json
{
  "default_voice": "British_Female",
  "tts_enabled": true,
  "arbiterEnginePath": "AIEngine/ArbiterEngine",
  "arbiterEnginePort": 8001,
  "git_author_name": "ArbiterUser",
  "git_author_email": "arbiter@local"
}
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `default_voice` | string | `"British_Female"` | Default TTS voice name (matched against `System.Speech` installed voices) |
| `tts_enabled` | bool | `true` | Enable or disable text-to-speech globally |
| `arbiterEnginePath` | string | `"AIEngine/ArbiterEngine"` | Relative or absolute path to the ArbiterEngine directory |
| `arbiterEnginePort` | int | `8001` | Port the Arbiter Engine server listens on |
| `git_author_name` | string | `"ArbiterUser"` | Git commit author name for auto-commits |
| `git_author_email` | string | `"arbiter@local"` | Git commit author email for auto-commits |

---

## ArbiterEngine — `AIEngine/ArbiterEngine/configs/config.toml`

Controls the full agentic engine runtime behaviour.

```toml
[server]
host = "127.0.0.1"
port = 8001
reload = false
log_level = "info"

[llm]
# Backend options: ollama | openai | anthropic | gemini | lmstudio |
#                  localai | openwebui | tabby | llamacpp | huggingface |
#                  vllm | cohere
backend = "ollama"
model = "llama3"
max_tokens = 4096
temperature = 0.7
timeout_s = 120

[agent]
# Number of retries for self-build code generation
max_retries = 3
# Default autonomy mode: manual | assist | semiauto | fullauto
autonomy_mode = "assist"
# Protected files that FullAuto mode must not modify
protected_files = ["config.toml", ".env", "settings.json"]

[self_build]
enabled = true
roadmap_path = "../../roadmap.json"
commit_tag = "[arbiter-self-build]"
# Maximum tasks the loop will attempt in one session
max_tasks_per_session = 5

[tools]
# Enable/disable individual tool groups
git = true
build = true
test = true
deploy = true
docker = true
web_search = false  # requires external network

[permissions]
# Which endpoints require approval in semiauto mode
require_approval = ["self-build/start", "deploy/run", "git/push"]
```

### Common Adjustments

**Switch to OpenAI backend:**

```toml
[llm]
backend = "openai"
model = "gpt-4o"
```

Set `OPENAI_API_KEY` in `.env`.

**Enable FullAuto self-build:**

```toml
[agent]
autonomy_mode = "fullauto"
```

**Increase token budget for large files:**

```toml
[llm]
max_tokens = 8192
```

---

## Environment Variables — `.env`

Create a `.env` file at the repository root. Values here override nothing already
set in the environment (they are "soft defaults").

```env
# Path to a local GGUF model file (used by llama-cpp backend)
ARBITER_MODEL_PATH=models/llama3-8b-q4.gguf

# Ollama server URL
OLLAMA_HOST=http://localhost:11434

# OpenAI
OPENAI_API_KEY=sk-...

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Gemini
GOOGLE_API_KEY=...

# Log level override (DEBUG | INFO | WARNING | ERROR)
ARBITER_LOG_LEVEL=INFO
```

---

## PythonBridge — No File Configuration

The PythonBridge (`fastapi_bridge.py`) is intentionally configuration-free — it
reads from `settings.json` (for port) and `.env` (for API keys and model paths).
All behavioural tuning is done via the engine settings above.

---

## Visual Studio Extension — Tools → Options → Arbiter AI

| Setting | Description |
|---------|-------------|
| Backend URL | URL of the active Arbiter backend (default: `http://127.0.0.1:8001`) |
| Auto-detect backend | Probe ports 8000 and 8001 on startup and use whichever responds |
| Inline completion trigger | Text prefix that activates inline completion (default: `// Arbiter:`) |
| Max response tokens | Limit tokens for inline completions |
| Auto-open chat panel | Open the chat panel automatically when a solution loads |

---

## Roadmap — `roadmap.json`

The machine-readable roadmap drives the self-build loop. It is updated
automatically by the loop after each task completes. See
[Roadmap](ROADMAP.md) for the human-readable version.

**Schema:**

```json
{
  "project": "ArbiterAI",
  "version": "1.1.0",
  "last_updated": "2026-03-24",
  "pillars": ["..."],
  "milestones": [
    {
      "id": "M0",
      "title": "Foundation",
      "status": "done",
      "tasks": [
        { "id": "M0-1", "title": "...", "status": "done" }
      ]
    }
  ]
}
```

**Task statuses:** `pending` | `in_progress` | `done` | `blocked`
