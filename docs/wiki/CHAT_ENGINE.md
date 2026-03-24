# Chat Engine

Arbiter's Chat Engine is Pillar 1 of the platform — a context-aware, multi-turn
conversational AI tightly integrated with your development workflow.

---

## Core Features

| Feature | Description |
|---------|-------------|
| Multi-turn history | Full conversation history per project stored in SQLite |
| Streaming responses | Token-by-token delivery via SSE or WebSocket |
| Persona system | Switch AI personality and focus (Coder, Teacher, Organizer, + custom) |
| Context injection | Active file, selection, and project auto-injected with every message |
| File attachment | Drag a file into chat for AI to read |
| Inline diff preview | See the exact changes before AI applies them |
| RAG / Archive codex | BM25 keyword search over your knowledge archive |
| Slash commands | `/build`, `/run`, `/test`, `/commit`, `/task`, `/agent`, `/search` |
| Code block actions | Apply, Copy, Save Snippet, Diff |
| Export | Export any conversation as Markdown |
| Full-text search | Search across all conversation history |
| Multi-agent | Spawn sub-agents for parallel tasks |
| Mermaid diagrams | AI generates architecture/flow diagrams |
| Voice output (TTS) | Hear AI responses read aloud |
| Voice input (STT) | Dictate messages via Whisper |
| Chat branching | Fork a conversation from any message |
| Templates | Start a chat from a predefined conversation template |
| Bookmarks | Bookmark important messages for quick access |
| AI feedback | Rate responses; Arbiter adapts its style |

---

## Personas

Personas shape the AI's tone, focus, and response style.

| Persona | Focus |
|---------|-------|
| **Arbiter** | General-purpose; balanced; default |
| **Coder** | Concise code generation; no fluff; code-first |
| **Teacher** | Detailed explanations; step-by-step; beginner-friendly |
| **Organizer** | Planning and tasks; structured output; checklists |
| *custom* | Fully user-defined system prompt |

### Switching Personas

Via the chat UI: click the persona badge next to the input box.

Via the API:
```http
POST /persona/my_project
{ "persona": "Coder" }
```

### Creating a Custom Persona

```http
POST /persona/custom
{
  "name": "SecurityExpert",
  "system_prompt": "You are a security-focused code reviewer. Identify vulnerabilities, suggest fixes, and explain risks concisely.",
  "tone": "formal",
  "avatar": "🔐"
}
```

---

## Slash Commands

Type `/` in the chat input to see all available commands.

| Command | Description |
|---------|-------------|
| `/build` | Run the project build |
| `/run` | Run the project entry point |
| `/test` | Run the test suite |
| `/commit <message>` | Stage all changes and commit |
| `/task <description>` | Create a task in the issues tracker |
| `/agent <task>` | Spawn an agentic loop for a specific task |
| `/search <query>` | Search the knowledge archive |
| `/summarize` | Summarize the current conversation |
| `/export` | Export the conversation as Markdown |
| `/clear` | Clear the current conversation (keeps history) |

---

## Context Injection

Every chat request automatically includes:

1. **Project name** — used to load the right SQLite history
2. **Active file path** — from the open editor tab
3. **Selected text** — highlighted code in the editor
4. **Persona system prompt** — shapes AI personality
5. **RAG context** — top-k archive entries matching the message

The AI always knows what file you are looking at and what you have selected.

---

## Voice I/O

### Text-to-Speech (TTS)

- Backend: `pyttsx3` (Python) or `System.Speech` (WPF)
- Enable: set `use_voice: true` in the chat request or toggle in settings
- Default voice: configured in `HostApp/Config/settings.json`

### Speech-to-Text (STT)

- Backend: OpenAI Whisper (local) or Windows Speech Recognition
- Use: press the microphone button in the chat UI or the WPF toolbar

---

## Code Block Actions

When the AI responds with a code block, action buttons appear:

| Action | Description |
|--------|-------------|
| **Apply** | Write the code directly to the active file |
| **Copy** | Copy to clipboard |
| **Save Snippet** | Save to `Memory/snippets.json` for reuse |
| **Diff** | Show a unified diff of what applying would change |

---

## Chat Branching

Fork a conversation at any point to explore alternatives:

```http
POST /chat/branch
{
  "project": "my_project",
  "message_id": "msg_42",
  "new_message": "What if we used a hash map instead?"
}
```

The original conversation is preserved; the branch becomes a separate thread.

---

## Conversation Templates

Start a conversation with a pre-built context template:

```http
GET /chat/templates
POST /chat/templates/apply
{ "template": "code_review", "project": "my_project" }
```

Available templates: `code_review`, `bug_hunt`, `architecture_design`,
`test_generation`, `documentation_sprint`, `performance_audit`.

---

## Multi-Agent Orchestration

Spawn sub-agents to handle parallel or specialized tasks:

```
/agent implement the caching layer in src/cache.py
```

The orchestrator assigns a Coder agent to that task while you continue
chatting in the main thread. Agent status appears in the Multi-Agent panel.

---

## Session Memory

Per-project key-value memory persists across sessions:

```
/remember database: PostgreSQL 15, schema at docs/schema.sql
```

Arbiter stores this and injects it into future conversations automatically.

---

## Analytics

```http
GET /chat/analytics
```

Returns:
- Messages per day
- Average response time
- Top personas used
- Most active projects
- Feedback scores
