"""Arbiter Engine Core Agent Loop."""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from core.config_loader import ConfigLoader
from core.logger import get_logger
from core.permission import PermissionSystem
from core.task_runner import TaskRunner
from core.tool_registry import ToolRegistry
from llm.base import BaseLLM

logger = get_logger(__name__)


@dataclass
class AgentState:
    prompt: str
    plan: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    results: list[Any] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = 20
    done: bool = False
    chat_history: list[dict[str, Any]] = field(default_factory=list)


class Agent:
    """Core agent that drives the prompt→plan→tool_call→execution→result loop."""

    def __init__(
        self,
        llm: BaseLLM,
        tool_registry: ToolRegistry,
        permission_system: PermissionSystem,
        task_runner: TaskRunner,
        config: ConfigLoader,
        project_path: str = "",
    ) -> None:
        self.llm = llm
        self.tools = tool_registry
        self.permissions = permission_system
        self.runner = task_runner
        self.config = config
        self._project_context = self._load_project_context(project_path)
        self._session_memory = self._load_session_memory(project_path)
        self._active_persona_prompt = self._load_active_persona_prompt()

    @staticmethod
    def _load_active_persona_prompt() -> str:
        try:
            from modules.ai_persona.src.ai_persona_tools import load_active_persona_prompt
            return load_active_persona_prompt()
        except Exception as exc:
            logger.debug("Could not load active persona: %s", exc)
            return ""

    @staticmethod
    def _load_session_memory(project_path: str) -> str:
        try:
            from pathlib import Path as _P
            import json as _json
            if project_path:
                mem_file = _P(project_path) / ".arbiter" / "session_memory.json"
            else:
                mem_file = _P(".arbiter") / "session_memory.json"
            if not mem_file.is_file():
                return ""
            mem: dict = _json.loads(mem_file.read_text(encoding="utf-8"))
            if not mem:
                return ""
            lines = [f"- {k}: {v}" for k, v in list(mem.items())[:20]]
            return "Session memory (facts from previous conversations):\n" + "\n".join(lines)
        except Exception as exc:
            logger.debug("Could not load session memory: %s", exc)
            return ""

    @staticmethod
    def _load_project_context(project_path: str) -> str:
        try:
            from modules.project_profile.src.profile_tools import load_project_context
            return load_project_context(project_path)
        except Exception as exc:
            logger.debug("Could not load project context: %s", exc)
            return ""

    def _retrieve_knowledge(self, query: str, project_path: str = "") -> str:
        try:
            from modules.knowledge.src.knowledge_tools import knowledge_search
            result = knowledge_search(query, project_path=project_path, top_k=3)
            chunks = result.get("results", [])
            if not chunks:
                return ""
            parts = ["Relevant documentation:"]
            for c in chunks:
                parts.append(f"[{c['source_label']}]\n{c['text']}")
            return "\n\n".join(parts)
        except Exception as exc:
            logger.debug("Knowledge retrieval failed: %s", exc)
            return ""

    def run(
        self,
        prompt: str,
        project_path: str = "",
        chat_history: list[dict[str, Any]] | None = None,
    ) -> str:
        state = AgentState(prompt=prompt)
        state.chat_history = chat_history or []
        knowledge = self._retrieve_knowledge(prompt, project_path)
        if knowledge:
            state.prompt = f"{knowledge}\n\n---\nTask: {prompt}"
        logger.info("Agent started. prompt=%r", prompt)
        while not state.done and state.iteration < state.max_iterations:
            state.iteration += 1
            logger.debug("Iteration %d", state.iteration)
            self._plan(state)
            tool_calls = self._select_tool_calls(state)
            if not tool_calls:
                state.done = True
                break
            for tc in tool_calls:
                result = self._execute_tool(tc, state)
                state.results.append(result)
                state.history.append({"tool": tc.get("name"), "result": result})
        final = self._finalize(state)
        logger.info("Agent finished after %d iterations.", state.iteration)
        return final

    def _plan(self, state: AgentState) -> None:
        messages = self._build_messages(state)
        response = self.llm.chat(messages)
        state.plan = self._parse_plan(response)
        logger.debug("Plan: %s", state.plan)

    def _select_tool_calls(self, state: AgentState) -> list[dict[str, Any]]:
        messages = self._build_messages(state, include_tools=True)
        tool_calls = self.llm.tool_call(messages, self.tools.list_tools())
        return tool_calls or []

    def _execute_tool(self, tool_call: dict[str, Any], state: AgentState) -> Any:
        name = tool_call.get("name", "")
        args = tool_call.get("arguments", {})
        if not isinstance(args, dict):
            logger.warning("Tool %r 'arguments' is %s, not a dict — coercing to {}.", name, type(args).__name__)
            args = {}
        if not self.permissions.is_allowed(name, args):
            logger.warning("Tool %r blocked by permission system.", name)
            return {"error": f"Permission denied for tool '{name}'"}
        tool = self.tools.get(name)
        if tool is None:
            return {"error": f"Unknown tool '{name}'"}
        return self.runner.run(tool, args)

    def _finalize(self, state: AgentState) -> str:
        messages = self._build_messages(state)
        if state.results:
            messages.append({"role": "user", "content": "Summarize the final result."})
        return self.llm.generate(messages)

    def _build_messages(self, state: AgentState, include_tools: bool = False) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self._system_prompt(include_tools)},
        ]
        for entry in state.chat_history:
            role = entry.get("role", "user")
            content = entry.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": state.prompt})
        for entry in state.history:
            messages.append(
                {"role": "assistant", "content": f"Tool {entry['tool']} returned: {entry['result']}"}
            )
        return messages

    def _system_prompt(self, include_tools: bool = False) -> str:
        if self._active_persona_prompt:
            base = self._active_persona_prompt
        else:
            base = (
                "You are Arbiter, the built-in AI assistant of the Arbiter IDE — "
                "a self-hosted, fully offline AI-powered development platform.\n\n"
                "## What you know about Arbiter\n"
                "Arbiter is a local-first IDE with a WPF native interface, AI chat panel, "
                "file explorer, git integration, build/test runners, voice TTS/STT, and a rich REST API. "
                "It runs on FastAPI and exposes every capability as an HTTP endpoint. "
                "The user interacts with you through the Chat panel in the Arbiter WPF application.\n\n"
                "## Arbiter capabilities you can help with\n"
                "- **Code generation & editing**: write, refactor, explain, or fix code in any language\n"
                "- **Build & test automation**: CMake/Make/Ninja builds, pytest/unittest, dotnet, npm\n"
                "- **File system**: read/write/copy/move/delete files and directories\n"
                "- **Git**: init, commit, push, pull, diff, log, branch management\n"
                "- **Project management**: multi-project workspace, templates, scaffolding, roadmap\n"
                "- **Package management**: pip, npm, cargo, gem, go install/list\n"
                "- **Image processing**: resize, convert, crop (Pillow)\n"
                "- **Audio processing**: convert, trim, normalise (FFmpeg/pydub)\n"
                "- **Archive & packaging**: ZIP/TAR/7z\n"
                "- **Documentation generation**: auto-generate Markdown/HTML docs from source\n"
                "- **Docker management**: build/run containers, view logs\n"
                "- **Remote deployment & SSH**: deploy to servers\n"
                "- **Database tools**: SQLite/SQL query and schema management\n"
                "- **CI/CD pipelines**: trigger and monitor CI runs\n"
                "- **Secret vault**: encrypted key-value secret storage\n"
                "- **Web search**: search the web for documentation and answers\n"
                "- **AI personas**: specialist AI roles (senior_developer, architect, etc.)\n"
                "- **Knowledge base**: project documentation RAG search\n"
                "- **Memory**: persistent key-value memory across sessions\n"
                "- **Voice**: TTS output and STT input\n"
                "- **Self-build**: autonomous self-improvement loop via roadmap tasks\n"
                "- **Plugin system**: drop Python files in plugins/ for auto-loaded custom tools\n\n"
                "## How to respond\n"
                "- You are CONTEXT-AWARE: you remember this entire conversation.\n"
                "- Respond concisely and helpfully. Use markdown with code blocks when showing code.\n"
                "- When the user asks about the project they have open, use context from the project profile.\n"
                "- Never say you are starting fresh or that you don't have context."
            )
        if self._project_context:
            base += f"\n\n{self._project_context}"
        if self._session_memory:
            base += f"\n\n{self._session_memory}"
        if include_tools:
            lines = []
            for t in self.tools.list_tools():
                props = t.get("arguments", {}).get("properties", {})
                required = set(t.get("arguments", {}).get("required", []))
                params = ", ".join(
                    f"{k}: {v.get('type', 'any')}{'*' if k in required else ''}"
                    for k, v in props.items()
                )
                desc = t.get("description", "")
                lines.append(f"- {t['name']}({params}): {desc}")
            base += "\n\nAvailable tools (* = required arg):\n" + "\n".join(lines)
        return base

    @staticmethod
    def _parse_plan(response: str) -> list[str]:
        lines = response.strip().splitlines()
        plan = []
        for line in lines:
            stripped = line.strip().lstrip("0123456789.-) ").strip()
            if stripped:
                plan.append(stripped)
        return plan
