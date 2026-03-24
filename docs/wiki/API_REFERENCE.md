# API Reference

Both backends (PythonBridge on port 8000 and ArbiterEngine on port 8001)
implement the same REST API contract. All clients — WPF app, Monaco IDE,
VS extension — work identically with either backend.

---

## Base URLs

| Mode | Base URL |
|------|----------|
| PythonBridge (lightweight) | `http://127.0.0.1:8000` |
| ArbiterEngine (full agentic) | `http://127.0.0.1:8001` |

---

## Chat

### `POST /chat`

Standard chat message with history.

**Request:**
```json
{
  "message": "How do I implement a binary search tree in Python?",
  "project": "my_project",
  "use_voice": false,
  "voice": "British_Female"
}
```

**Response:**
```json
{
  "reply": "Here's a binary search tree implementation...",
  "persona": "Coder",
  "model": "llama3"
}
```

---

### `POST /assistant/chat`

IDE-aware chat. Automatically injects active file content and selection context.

**Request:**
```json
{
  "message": "Explain this function",
  "project": "my_project",
  "file_path": "src/utils.py",
  "selection": "def calculate_total(items):\n    return sum(items)",
  "use_voice": false
}
```

---

### `POST /assistant/chat/agentic`

Triggers the full agentic loop: plan → identify files → write code → test → commit.

**Request:**
```json
{
  "task": "Add input validation to the login endpoint",
  "project": "my_project",
  "mode": "assist"
}
```

---

### `GET /history/{project}`

Get conversation history for a project.

**Response:**
```json
{
  "history": [
    { "role": "user", "content": "...", "timestamp": "..." },
    { "role": "assistant", "content": "...", "timestamp": "..." }
  ]
}
```

---

### `POST /history/{project}/export`

Export conversation history as Markdown.

---

### `GET /history/search?q=<query>`

Full-text search across all conversation history.

---

### `GET /personas`

List all available personas.

**Response:**
```json
{
  "personas": ["Arbiter", "Coder", "Teacher", "Organizer", "custom_1"]
}
```

---

### `POST /persona/{project}`

Set active persona for a project.

**Request:** `{ "persona": "Coder" }`

---

### `POST /persona/custom`

Create or update a custom persona.

**Request:**
```json
{
  "name": "Reviewer",
  "system_prompt": "You are a senior code reviewer. Be concise and focus on correctness and performance.",
  "tone": "formal",
  "avatar": "🔍"
}
```

---

## AI Code Actions

### `POST /ai/action`

Perform an AI action on code.

**Request:**
```json
{
  "action": "explain | fix | refactor | docstring | tests",
  "code": "def foo(x):\n    return x*2",
  "context": "Python function in src/utils.py",
  "project": "my_project"
}
```

---

### `POST /ai/complete`

Inline code completion. Returns the completion for the given prefix.

---

### `POST /ai/propose`

Propose a change to a file. Returns a unified diff.

**Request:**
```json
{
  "file_path": "src/utils.py",
  "instruction": "Add type hints to all function signatures",
  "project": "my_project"
}
```

---

### `POST /ai/review`

Structured code review of a file or snippet.

---

### `POST /ai/diff`

Apply a natural language instruction to a file and return the resulting diff.

---

### `POST /ai/diagram`

Generate a Mermaid diagram from code or description.

---

### `POST /docgen/generate`

Generate documentation (docstrings, README, inline comments) for a file.

---

## Scaffold & Refactor

### `POST /scaffold/module`

Generate a module boilerplate.

**Request:** `{ "name": "auth", "type": "python_module", "project": "my_project" }`

---

### `POST /scaffold/plugin`

Generate plugin scaffold.

---

### `POST /scaffold/tests`

Generate test file for an existing module.

---

### `GET /templates`

List available project templates.

---

### `POST /templates/apply`

Apply a template to the active project.

---

### `POST /refactor/find-replace`

Regex find-replace across all project files.

**Request:**
```json
{
  "project": "my_project",
  "pattern": "old_function_name",
  "replacement": "new_function_name",
  "glob": "**/*.py"
}
```

---

### `POST /refactor/rename`

Whole-word symbol rename across project files.

---

## Build, Run, Test

### `POST /build`

Build the project using auto-detected build command.

**Request:** `{ "project": "my_project", "command": "" }`

---

### `POST /run`

Run the project entry point.

---

### `POST /test`

Run the test suite.

---

### `WS /ws/run`

WebSocket for streaming build output in real time.

---

### `WS /ws/pty`

PTY terminal WebSocket — full interactive shell.

---

### `WS /ws/chat`

WebSocket chat stream — real-time token delivery.

---

## Git

```http
GET  /git/status              # Working tree status
POST /git/stage               # Stage files: { "files": ["src/foo.py"] }
POST /git/commit              # Commit: { "message": "..." }
GET  /git/log                 # Commit history
GET  /git/diff                # File or commit diff
POST /git/clone               # Clone remote: { "url": "...", "dest": "..." }
```

---

## Archive & Library

```http
GET  /archive                 # Full archive listing
GET  /archive/search?q=       # Keyword search over the codex
POST /archive/rebuild         # Re-index all library paths
GET  /archive/export          # Export codex as Markdown
GET  /library                 # List library paths
POST /library                 # Add library path: { "path": "..." }
```

---

## DevOps

```http
GET  /docker/containers       # List Docker containers
POST /docker/build            # Build image: { "tag": "...", "path": "..." }
POST /docker/run              # Run container
POST /ci/run                  # Trigger CI run
GET  /ci/runs                 # CI run history
POST /deploy/config           # Create deploy config
POST /deploy/run              # Execute deployment
GET  /deploy/history          # Deployment run history
POST /queue/task              # Enqueue background command
GET  /queue/stats             # Task queue statistics
POST /cron/job                # Register cron job
```

---

## Self-Build

```http
POST /self-build/start        # { "mode": "assist|semiauto|fullauto" }
POST /self-build/stop
GET  /self-build/status
POST /self-build/approve      # { "session_id": "..." }
POST /self-build/reject       # { "session_id": "...", "reason": "..." }
GET  /self-build/log
GET  /self-build/roadmap
```

---

## Health & Metrics

```http
GET  /health                  # { "status": "ok", "model": "llama3", ... }
GET  /metrics                 # Prometheus-compatible metrics
GET  /model/status            # LLM backend status and loaded model info
```

---

## Enhanced Chat (M10)

```http
POST /chat/branch             # Create a chat branch from a message
GET  /chat/templates          # List conversation templates
POST /chat/feedback           # Rate a response: { "message_id": "...", "rating": 1-5 }
POST /chat/bookmark           # Bookmark a message
POST /chat/image              # Send an image as context (base64)
POST /chat/context/file       # Attach file to chat context
GET  /chat/stream             # SSE streaming chat
POST /chat/thread             # Create a new conversation thread
GET  /chat/analytics          # Chat usage analytics
POST /chat/summarize          # Summarize a conversation
```

---

## Advanced AI (M11)

```http
POST /ai/route                # Multi-model routing — choose best model for task
POST /agents/specialist       # Spawn a specialist agent (security, perf, docs, etc.)
POST /ai/generate/from-requirements  # Code generation from natural language requirements
POST /knowledge/scan          # Scan a codebase and build knowledge graph
GET  /knowledge/graph         # Retrieve knowledge graph as JSON
POST /knowledge/search        # Semantic search over knowledge graph
POST /ai/tests/generate       # AI test intelligence — generate comprehensive tests
POST /search/semantic         # Semantic search across all project files
POST /persona/feedback        # Submit feedback on persona responses
POST /persona/adapt           # Adapt persona based on usage patterns
POST /pair/start              # Start a pair-programming session
POST /pair/analyze            # Analyze code in a pair session
```

---

## Analysis & Quality (M14)

```http
POST /analysis/lint           # Lint the project files
POST /analysis/deps/security  # Dependency security audit
POST /analysis/complexity     # Code complexity analysis
POST /analysis/duplicates     # Find duplicate code
POST /docs/generate           # AI documentation generation
POST /analysis/coverage       # Test coverage report
POST /analysis/profile        # Performance profiling
GET  /review/workflow         # Code review workflow status
```

---

## Issues Tracker

```http
POST /issues/create           # Create an issue
GET  /issues/list             # List all issues
GET  /issues/{id}             # Get issue details
POST /issues/close            # Close an issue
POST /issues/comment          # Add a comment to an issue
```

---

## Error Responses

All endpoints return standard HTTP status codes:

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Bad request (invalid parameters) |
| 404 | Resource not found |
| 422 | Validation error (Pydantic) |
| 500 | Internal server error |
| 503 | LLM backend unavailable |

Error body:
```json
{ "detail": "Human-readable error message" }
```
