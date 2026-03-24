# Contributing

Arbiter is an active solo project, but issues and pull requests are very welcome.
Please read this guide before contributing.

---

## Code Conventions

### Python

| Rule | Example |
|------|---------|
| Style | PEP 8 / Black defaults (88-char line length) |
| Naming | `snake_case` for functions, variables, modules |
| Classes | `PascalCase` |
| Constants | `UPPER_SNAKE_CASE` |
| Type hints | Always use (Python 3.10+ union syntax: `str \| None`) |
| Docstrings | Google-style docstrings for public functions |

### C# (WPF / VSIX)

| Rule | Example |
|------|---------|
| Naming | `PascalCase` for classes, methods, properties |
| Fields | `_camelCase` (underscore prefix for private) |
| Constants | `PascalCase` |
| Async methods | Always suffix `Async` |
| Null handling | Use nullable reference types (`string?`) |

### JSON Config Files

- lowercase keys with underscores (`"max_tokens"`)
- No trailing commas

### Markdown

- Title Case headings with spaces
- ATX-style headings (`##`, not underlines)

---

## Adding a New API Endpoint

New endpoints must be added to **both** backends for consistency:

1. `AIEngine/PythonBridge/fastapi_bridge.py` (port 8000)
2. `AIEngine/ArbiterEngine/server.py` (port 8001)

Follow the existing Pydantic model + FastAPI route pattern:

```python
class MyRequest(BaseModel):
    project: str
    input: str

@app.post("/my/endpoint")
async def my_endpoint(req: MyRequest):
    _validate_project_name(req.project)
    # ...
    return {"result": "..."}
```

Update `docs/wiki/API_REFERENCE.md` with the new endpoint.

---

## Adding a New VSIX Component

1. Register it in `ArbiterPackage.cs`
2. Follow the VS Package pattern (inherit from `ToolWindowPane` for panels)
3. Add keyboard shortcut if applicable (`ArbiterCommands.cs`)
4. Document in `docs/wiki/VS_EXTENSION.md`

---

## Adding a Roadmap Task

Edit `roadmap.json` and add a task to the appropriate milestone:

```json
{
  "id": "M15-1",
  "title": "Short task title",
  "description": "Detailed description. Be specific — the self-build loop reads this.",
  "status": "pending",
  "files_hint": ["server.py"],
  "acceptance_criteria": [
    "Endpoint /new/thing returns 200",
    "All existing tests still pass"
  ]
}
```

---

## Running Tests

```bash
# Python tests (ArbiterEngine)
cd AIEngine/ArbiterEngine
pytest

# .NET tests (HostApp, VSIX)
dotnet test Arbiter.sln
```

---

## Git Commit Format

| Type | Example |
|------|---------|
| Feature | `feat: add chat branching endpoint` |
| Fix | `fix: resolve server crash on large context` |
| Docs | `docs: update API reference for M14 endpoints` |
| Refactor | `refactor: extract log path resolution to helper` |
| Self-build | `[arbiter-self-build] M10-2: Conversation templates` |

Self-build commits are automatically tagged `[arbiter-self-build]` by the loop
so they are distinguishable from human commits.

---

## Submitting a PR

1. Fork the repository
2. Create a branch: `git checkout -b feat/my-feature`
3. Make changes and add tests
4. Run the test suite: `pytest && dotnet test`
5. Open a PR against `main` describing what you changed and why

---

## Code of Conduct

Be respectful, constructive, and helpful. Focus on the code, not the person.
