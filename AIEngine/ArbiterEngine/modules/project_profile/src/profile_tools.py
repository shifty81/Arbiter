"""Project Profile module — per-project AI personas, tech-stack awareness, and rule sets.

Each project stores its configuration in:
    {project_path}/.swissagent/profile.json   — AI persona & tech stack
    {project_path}/.swissagent/rules.json     — behavioral constraints
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── Pre-built knowledge packs (curated doc URLs per tech) ─────────────────────
KNOWLEDGE_PACKS: dict[str, list[dict[str, str]]] = {
    "python": [
        {"url": "https://docs.python.org/3/library/functions.html", "label": "Python built-in functions"},
        {"url": "https://docs.python.org/3/library/pathlib.html", "label": "Python pathlib"},
        {"url": "https://peps.python.org/pep-0008/", "label": "PEP 8 style guide"},
        {"url": "https://peps.python.org/pep-0257/", "label": "PEP 257 docstring conventions"},
    ],
    "fastapi": [
        {"url": "https://fastapi.tiangolo.com/tutorial/", "label": "FastAPI tutorial"},
        {"url": "https://fastapi.tiangolo.com/advanced/", "label": "FastAPI advanced"},
    ],
    "javascript": [
        {"url": "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference", "label": "MDN JS Reference"},
        {"url": "https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API", "label": "MDN Fetch API"},
    ],
    "typescript": [
        {"url": "https://www.typescriptlang.org/docs/handbook/intro.html", "label": "TypeScript Handbook"},
    ],
    "rust": [
        {"url": "https://doc.rust-lang.org/book/", "label": "The Rust Book"},
        {"url": "https://doc.rust-lang.org/std/", "label": "Rust std library"},
    ],
    "cpp": [
        {"url": "https://en.cppreference.com/w/cpp", "label": "cppreference C++"},
    ],
    "react": [
        {"url": "https://react.dev/reference/react", "label": "React API Reference"},
        {"url": "https://react.dev/learn", "label": "React learn guide"},
    ],
    "go": [
        {"url": "https://pkg.go.dev/std", "label": "Go standard library"},
        {"url": "https://go.dev/doc/effective_go", "label": "Effective Go"},
    ],
}

# Tech-stack detection: file marker → (tech label, knowledge pack key)
_DETECTORS: list[tuple[str, str, str]] = [
    ("package.json",   "Node.js / JavaScript", "javascript"),
    ("tsconfig.json",  "TypeScript",            "typescript"),
    ("Cargo.toml",     "Rust",                  "rust"),
    ("pyproject.toml", "Python",                "python"),
    ("setup.py",       "Python",                "python"),
    ("CMakeLists.txt", "C++",                   "cpp"),
    ("go.mod",         "Go",                    "go"),
    ("pom.xml",        "Java (Maven)",          ""),
    ("build.gradle",   "Java/Kotlin (Gradle)",  ""),
]

# Default AI personas per tech stack
_PERSONAS: dict[str, str] = {
    "Python": (
        "You are an expert Python developer. "
        "Follow PEP 8 and PEP 257. Always use type hints. Write comprehensive docstrings. "
        "Prefer pathlib over os.path. Use f-strings. Keep functions small and focused."
    ),
    "Rust": (
        "You are an expert Rust developer. "
        "Prioritise memory safety and zero-cost abstractions. "
        "Prefer iterators over loops. Handle all Result/Option types explicitly. "
        "Write idiomatic Rust with clear ownership semantics."
    ),
    "C++": (
        "You are an expert C++ developer. "
        "Target C++17 or later. Prefer smart pointers over raw pointers. "
        "Use RAII. Avoid undefined behaviour. Write const-correct code."
    ),
    "JavaScript": (
        "You are an expert JavaScript developer. "
        "Use modern ES2020+ syntax. Prefer async/await over callbacks. "
        "Avoid var; use const by default, let when needed."
    ),
    "TypeScript": (
        "You are an expert TypeScript developer. "
        "Use strict mode. Define explicit types for all public APIs. "
        "Prefer interfaces over type aliases for objects."
    ),
    "Go": (
        "You are an expert Go developer. "
        "Follow effective Go guidelines. Handle errors explicitly — never ignore them. "
        "Keep interfaces small. Write table-driven tests."
    ),
}


# ── Path helpers ───────────────────────────────────────────────────────────────

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _sa_dir(project_path: str = "") -> Path:
    root = _repo_root()
    base = (root / project_path) if project_path else (root / "workspace")
    d = base / ".swissagent"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _profile_path(project_path: str = "") -> Path:
    return _sa_dir(project_path) / "profile.json"


def _rules_path(project_path: str = "") -> Path:
    return _sa_dir(project_path) / "rules.json"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ── Public tool functions ──────────────────────────────────────────────────────

def profile_get(project_path: str = "") -> dict[str, Any]:
    """Read the AI profile for a project."""
    profile = _load_json(_profile_path(project_path))
    rules_data = _load_json(_rules_path(project_path))
    rules = rules_data.get("rules", [])
    return {
        "project_path": project_path or "workspace (root)",
        "profile": profile,
        "rule_count": len(rules),
        "has_profile": bool(profile),
        "system_prompt_preview": _build_system_prompt(profile, rules)[:500] + "…" if profile else "(no profile set)",
    }


def profile_set(
    project_path: str = "",
    project_name: str = "",
    description: str = "",
    tech_stack: list[str] | None = None,
    ai_persona: str = "",
    coding_standards: str = "",
    llm_backend: str = "",
    knowledge_sources: list[str] | None = None,
) -> dict[str, Any]:
    """Create or update the AI profile for a project."""
    existing = _load_json(_profile_path(project_path))
    updated = {**existing}

    if project_name:
        updated["project_name"] = project_name
    if description:
        updated["description"] = description
    if tech_stack is not None:
        updated["tech_stack"] = tech_stack
        # Auto-suggest persona if not overridden
        if not ai_persona and not existing.get("ai_persona"):
            for tech in tech_stack:
                if tech in _PERSONAS:
                    updated["ai_persona"] = _PERSONAS[tech]
                    break
    if ai_persona:
        updated["ai_persona"] = ai_persona
    if coding_standards:
        updated["coding_standards"] = coding_standards
    if llm_backend:
        updated["llm_backend"] = llm_backend
    if knowledge_sources is not None:
        updated["knowledge_sources"] = knowledge_sources

    updated["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Suggest knowledge packs based on tech stack
    suggested_packs: list[dict[str, str]] = []
    for tech in updated.get("tech_stack", []):
        key = tech.lower().split("/")[0].split(" ")[0]
        suggested_packs.extend(KNOWLEDGE_PACKS.get(key, []))

    _save_json(_profile_path(project_path), updated)

    return {
        "success": True,
        "project_path": project_path or "workspace (root)",
        "profile": updated,
        "suggested_knowledge_packs": suggested_packs[:6],
        "message": (
            f"Profile saved for '{updated.get('project_name', project_path)}'. "
            + (f"Suggested {len(suggested_packs)} knowledge sources to fetch." if suggested_packs else "")
        ),
    }


def profile_detect(project_path: str) -> dict[str, Any]:
    """Auto-detect tech stack by scanning project files."""
    root = _repo_root()
    target = root / project_path
    if not target.is_dir():
        return {"error": f"Directory not found: {project_path}"}

    detected_stack: list[str] = []
    suggested_knowledge: list[dict[str, str]] = []

    for marker, tech_label, pack_key in _DETECTORS:
        if (target / marker).is_file():
            if tech_label not in detected_stack:
                detected_stack.append(tech_label)
            if pack_key and pack_key in KNOWLEDGE_PACKS:
                for item in KNOWLEDGE_PACKS[pack_key]:
                    if item not in suggested_knowledge:
                        suggested_knowledge.append(item)

    # Detect frameworks from package.json
    pkg = target / "package.json"
    if pkg.is_file():
        try:
            pkg_data = json.loads(pkg.read_text(encoding="utf-8"))
            deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
            for fw, tech in [("react", "React"), ("vue", "Vue.js"), ("svelte", "Svelte"),
                             ("next", "Next.js"), ("express", "Express.js")]:
                if fw in deps and tech not in detected_stack:
                    detected_stack.append(tech)
                    if fw in KNOWLEDGE_PACKS:
                        suggested_knowledge.extend(KNOWLEDGE_PACKS[fw])
        except Exception:
            pass

    # Auto-select persona
    ai_persona = ""
    for tech in detected_stack:
        key = tech.split("/")[0].split(" ")[0]
        if key in _PERSONAS:
            ai_persona = _PERSONAS[key]
            break

    return {
        "project_path": project_path,
        "detected_tech_stack": detected_stack,
        "ai_persona_suggestion": ai_persona,
        "suggested_knowledge_sources": suggested_knowledge[:8],
        "message": (
            f"Detected: {', '.join(detected_stack) or 'unknown'}. "
            "Call profile_set with this info to configure the AI for this project."
        ),
    }


def rules_get(project_path: str = "") -> dict[str, Any]:
    """Get all rules for a project."""
    data = _load_json(_rules_path(project_path))
    rules = data.get("rules", [])
    by_type: dict[str, list] = {"must": [], "must_not": [], "prefer": []}
    for r in rules:
        by_type.setdefault(r.get("type", "prefer"), []).append(r)
    return {
        "project_path": project_path or "workspace (root)",
        "total_rules": len(rules),
        "rules_by_type": by_type,
        "rules": rules,
    }


def rules_add(
    rule: str,
    rule_type: str,
    project_path: str = "",
) -> dict[str, Any]:
    """Add a rule to the project rule set."""
    valid_types = {"must", "must_not", "prefer"}
    if rule_type not in valid_types:
        return {"error": f"rule_type must be one of {sorted(valid_types)}"}

    data = _load_json(_rules_path(project_path))
    rules = data.get("rules", [])

    rule_id = "r" + uuid.uuid4().hex[:8]
    new_rule = {
        "id": rule_id,
        "type": rule_type,
        "rule": rule,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    rules.append(new_rule)
    data["rules"] = rules
    _save_json(_rules_path(project_path), data)

    return {
        "success": True,
        "rule": new_rule,
        "total_rules": len(rules),
        "message": f"Rule added: [{rule_type.upper()}] {rule}",
    }


def rules_remove(rule_id: str, project_path: str = "") -> dict[str, Any]:
    """Remove a rule by ID."""
    data = _load_json(_rules_path(project_path))
    rules = data.get("rules", [])
    before = len(rules)
    data["rules"] = [r for r in rules if r["id"] != rule_id]
    if len(data["rules"]) == before:
        return {"error": f"Rule '{rule_id}' not found."}
    _save_json(_rules_path(project_path), data)
    return {"success": True, "removed_rule_id": rule_id, "remaining_rules": len(data["rules"])}


# ── Shared helper used by core/agent.py ───────────────────────────────────────

def _build_system_prompt(profile: dict[str, Any], rules: list[dict[str, Any]]) -> str:
    """Build the project-specific addition to the agent system prompt."""
    parts: list[str] = []

    if profile.get("project_name"):
        parts.append(f"Project: {profile['project_name']}.")
    if profile.get("description"):
        parts.append(f"Project description: {profile['description']}.")
    if profile.get("tech_stack"):
        parts.append(f"Tech stack: {', '.join(profile['tech_stack'])}.")
    if profile.get("ai_persona"):
        parts.append(profile["ai_persona"])
    if profile.get("coding_standards"):
        parts.append(f"Coding standards: {profile['coding_standards']}.")

    must = [r["rule"] for r in rules if r.get("type") == "must"]
    must_not = [r["rule"] for r in rules if r.get("type") == "must_not"]
    prefer = [r["rule"] for r in rules if r.get("type") == "prefer"]

    if must:
        parts.append("You MUST: " + "; ".join(must) + ".")
    if must_not:
        parts.append("You MUST NOT: " + "; ".join(must_not) + ".")
    if prefer:
        parts.append("You SHOULD (prefer): " + "; ".join(prefer) + ".")

    return "\n".join(parts)


def load_project_context(project_path: str = "") -> str:
    """Load full profile + rules as a system prompt string. Called by the agent."""
    profile = _load_json(_profile_path(project_path))
    rules_data = _load_json(_rules_path(project_path))
    rules = rules_data.get("rules", [])
    return _build_system_prompt(profile, rules)
