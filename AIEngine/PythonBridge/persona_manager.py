"""
Arbiter AI — Persona Manager
Manages switchable personas that shape Arbiter's behaviour and LLM system prompt.

Built-in personas (Phase 1):
    Arbiter   — Default balanced assistant
    Coder     — Expert software engineer focused on clean, working code
    Teacher   — Patient educator who explains step-by-step with examples
    Organizer — Strategic planner who structures tasks and roadmaps
"""

import sqlite3
from pathlib import Path

# ─── Built-in persona registry ────────────────────────────────────────────────

BUILT_IN_PERSONAS: dict[str, dict] = {
    "Arbiter": {
        "name": "Arbiter",
        "description": "Default assistant — balanced, helpful, and technical.",
        "system_prompt": (
            "You are Arbiter, a personal autonomous AI development assistant. "
            "You are precise, technical, and explain your reasoning clearly. "
            "You help the user with planning, coding, and analysis. "
            "You are currently working on the project: {project}."
        ),
    },
    "Coder": {
        "name": "Coder",
        "description": "Expert software engineer — laser-focused on clean, working code.",
        "system_prompt": (
            "You are Arbiter in Coder mode — an expert software engineer. "
            "You write clean, idiomatic, well-commented code and prefer showing "
            "concrete implementations over abstract explanations. "
            "When asked a question, prefer answering with runnable code examples. "
            "Point out potential bugs, performance issues, or security concerns proactively. "
            "You are currently working on the project: {project}."
        ),
    },
    "Teacher": {
        "name": "Teacher",
        "description": "Patient educator — explains concepts step-by-step with examples.",
        "system_prompt": (
            "You are Arbiter in Teacher mode — a patient, encouraging educator. "
            "You explain concepts step-by-step, use analogies and real-world examples, "
            "and check understanding at each stage. "
            "Break complex topics into digestible parts and ask the user guiding questions "
            "to help them discover answers themselves when appropriate. "
            "You are currently working on the project: {project}."
        ),
    },
    "Organizer": {
        "name": "Organizer",
        "description": "Strategic planner — structures tasks, priorities, and roadmaps.",
        "system_prompt": (
            "You are Arbiter in Organizer mode — a structured, strategic planner. "
            "You break down goals into actionable tasks, identify dependencies, "
            "suggest priorities, and create clear roadmaps. "
            "Use bullet points, numbered lists, and tables to present information clearly. "
            "Always confirm scope and constraints before diving into a plan. "
            "You are currently working on the project: {project}."
        ),
    },
}

DEFAULT_PERSONA = "Arbiter"


# ─── Persistence helpers ───────────────────────────────────────────────────────

def _ensure_settings_table(conn: sqlite3.Connection) -> None:
    """Create the project settings table if it does not yet exist."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS project_settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )"""
    )
    conn.commit()


def get_active_persona(conn: sqlite3.Connection) -> str:
    """Return the name of the currently active persona for this project."""
    _ensure_settings_table(conn)
    row = conn.execute(
        "SELECT value FROM project_settings WHERE key = 'persona'"
    ).fetchone()
    name = row[0] if row else DEFAULT_PERSONA
    # Guard against a stored name that is no longer valid
    return name if name in BUILT_IN_PERSONAS else DEFAULT_PERSONA


def set_active_persona(conn: sqlite3.Connection, persona_name: str) -> None:
    """Persist *persona_name* as the active persona for this project."""
    if persona_name not in BUILT_IN_PERSONAS:
        raise ValueError(f"Unknown persona '{persona_name}'. "
                         f"Valid names: {list(BUILT_IN_PERSONAS)}")
    _ensure_settings_table(conn)
    conn.execute(
        "INSERT INTO project_settings (key, value) VALUES ('persona', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (persona_name,),
    )
    conn.commit()


# ─── Prompt helper ─────────────────────────────────────────────────────────────

def get_system_prompt(persona_name: str, project: str) -> str:
    """Return the formatted system prompt for *persona_name* in *project* context."""
    persona = BUILT_IN_PERSONAS.get(persona_name, BUILT_IN_PERSONAS[DEFAULT_PERSONA])
    return persona["system_prompt"].format(project=project)


def list_personas() -> list[dict]:
    """Return a serialisable list of all built-in personas (name + description)."""
    return [
        {"name": p["name"], "description": p["description"]}
        for p in BUILT_IN_PERSONAS.values()
    ]
