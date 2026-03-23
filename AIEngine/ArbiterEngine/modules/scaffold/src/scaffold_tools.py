"""Scaffold module — generate new modules, plugins, and tests from descriptions.

Provides:
  scaffold_module  — create a new capability module skeleton
  scaffold_plugin  — create a new plugin skeleton
  scaffold_tests   — generate pytest tests for an existing module
  roadmap_add_task — add a task to the self-development roadmap (alias)
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── Helpers ────────────────────────────────────────────────────────────────────

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _slug(name: str) -> str:
    """Convert a human name to a safe lowercase identifier (snake_case)."""
    s = re.sub(r"[^a-zA-Z0-9]+", "_", name.lower()).strip("_")
    return s or "module"


# ── scaffold_module ────────────────────────────────────────────────────────────

def scaffold_module(
    name: str,
    description: str,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a new SwissAgent capability module skeleton.

    Generates:
      modules/{name}/module.json
      modules/{name}/tools.json
      modules/{name}/src/__init__.py
      modules/{name}/src/{name}_tools.py
    """
    slug = _slug(name)
    mod_dir = _repo_root() / "modules" / slug
    if mod_dir.exists():
        return {"error": f"Module '{slug}' already exists at {mod_dir}"}

    src_dir = mod_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    # module.json
    (mod_dir / "module.json").write_text(
        json.dumps({"name": slug, "version": "0.1.0", "description": description, "dependencies": []},
                   indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Default tool if none provided
    if not tools:
        tools = [
            {
                "name": f"{slug}_run",
                "description": f"Run the main {slug} operation.",
                "module": slug,
                "function": f"modules.{slug}.src.{slug}_tools.{slug}_run",
                "arguments": {
                    "type": "object",
                    "properties": {
                        "input": {"type": "string", "description": "Input for the operation"},
                    },
                    "required": ["input"],
                },
            }
        ]
    else:
        # Ensure each tool has module/function fields pointing at the right place
        for t in tools:
            t.setdefault("module", slug)
            if "function" not in t:
                fn = _slug(t.get("name", f"{slug}_run"))
                t["function"] = f"modules.{slug}.src.{slug}_tools.{fn}"

    (mod_dir / "tools.json").write_text(
        json.dumps(tools, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # src/__init__.py
    (src_dir / "__init__.py").write_text(
        f'"""{slug} module."""\nfrom __future__ import annotations\n',
        encoding="utf-8",
    )

    # src/{slug}_tools.py — generate stubs for each tool
    lines = [
        f'"""{description}"""',
        "from __future__ import annotations",
        "from typing import Any",
        "",
    ]
    for t in tools:
        fn_name = t["function"].rsplit(".", 1)[-1]
        params = list(t.get("arguments", {}).get("properties", {}).keys())
        param_str = ", ".join(params) if params else ""
        lines += [
            "",
            f"def {fn_name}({param_str}) -> dict[str, Any]:",
            f'    """{ t.get("description", fn_name) }"""',
            "    # TODO: implement",
            f'    return {{"status": "not_implemented", "tool": "{fn_name}"}}',
        ]

    (src_dir / f"{slug}_tools.py").write_text("\n".join(lines) + "\n", encoding="utf-8")

    created_files = [
        str(p.relative_to(_repo_root()))
        for p in [
            mod_dir / "module.json",
            mod_dir / "tools.json",
            src_dir / "__init__.py",
            src_dir / f"{slug}_tools.py",
        ]
    ]
    return {
        "status": "created",
        "module": slug,
        "path": str(mod_dir.relative_to(_repo_root())),
        "files": created_files,
        "tools_count": len(tools),
    }


# ── scaffold_plugin ────────────────────────────────────────────────────────────

def scaffold_plugin(
    name: str,
    description: str,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a new SwissAgent plugin skeleton.

    Generates:
      plugins/{name}/plugin.json
      plugins/{name}/tools.json
      plugins/{name}/{name}_plugin.py
    """
    slug = _slug(name)
    plugin_dir = _repo_root() / "plugins" / slug
    if plugin_dir.exists():
        return {"error": f"Plugin '{slug}' already exists at {plugin_dir}"}

    plugin_dir.mkdir(parents=True, exist_ok=True)

    # plugin.json
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {"name": slug, "version": "0.1.0", "description": description, "author": ""},
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    if not tools:
        tools = [
            {
                "name": f"{slug}_run",
                "description": f"Run the {slug} plugin.",
                "module": slug,
                "function": f"plugins.{slug}.{slug}_plugin.{slug}_run",
                "arguments": {
                    "type": "object",
                    "properties": {
                        "input": {"type": "string", "description": "Input for the plugin"},
                    },
                    "required": ["input"],
                },
            }
        ]

    (plugin_dir / "tools.json").write_text(
        json.dumps(tools, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # main plugin file
    lines = [
        f'"""{description}"""',
        "from __future__ import annotations",
        "from typing import Any",
        "",
    ]
    for t in tools:
        fn_name = t["function"].rsplit(".", 1)[-1]
        params = list(t.get("arguments", {}).get("properties", {}).keys())
        param_str = ", ".join(params) if params else ""
        lines += [
            "",
            f"def {fn_name}({param_str}) -> dict[str, Any]:",
            f'    """{ t.get("description", fn_name) }"""',
            "    # TODO: implement",
            f'    return {{"status": "not_implemented", "plugin": "{slug}", "tool": "{fn_name}"}}',
        ]

    (plugin_dir / f"{slug}_plugin.py").write_text("\n".join(lines) + "\n", encoding="utf-8")

    created_files = [
        str(p.relative_to(_repo_root()))
        for p in [
            plugin_dir / "plugin.json",
            plugin_dir / "tools.json",
            plugin_dir / f"{slug}_plugin.py",
        ]
    ]
    return {
        "status": "created",
        "plugin": slug,
        "path": str(plugin_dir.relative_to(_repo_root())),
        "files": created_files,
        "tools_count": len(tools),
    }


# ── scaffold_tests ─────────────────────────────────────────────────────────────

def scaffold_tests(module_name: str, output_path: str = "") -> dict[str, Any]:
    """Generate a pytest test skeleton for an existing module.

    Reads the module's tools.json to discover available tools and writes
    a test file with one stub test per tool.
    """
    slug = _slug(module_name)
    root = _repo_root()

    # Look in modules/ first, then plugins/
    for base in (root / "modules", root / "plugins"):
        tools_json = base / slug / "tools.json"
        if tools_json.exists():
            break
    else:
        return {"error": f"Module or plugin '{slug}' not found (no tools.json)"}

    tools: list[dict[str, Any]] = json.loads(tools_json.read_text(encoding="utf-8"))

    # Determine output path
    if output_path:
        out = Path(output_path)
    else:
        out = root / "tests" / f"test_{slug}.py"

    if out.exists():
        return {"error": f"Test file already exists: {out}"}

    lines = [
        f'"""Tests for the {slug} module — auto-generated by scaffold_tests."""',
        "from __future__ import annotations",
        "import pytest",
        "",
    ]

    for t in tools:
        fn_path = t.get("function", "")
        fn_name = fn_path.rsplit(".", 1)[-1] if fn_path else t["name"]
        tool_name = t["name"]
        props = t.get("arguments", {}).get("properties", {})
        required = t.get("arguments", {}).get("required", [])

        lines += [
            "",
            f"def test_{tool_name}(tmp_path):",
            f'    """Stub test for {tool_name}."""',
        ]
        if fn_path:
            module_import = fn_path.rsplit(".", 1)[0]
            lines.append(f"    from {module_import} import {fn_name}")
        lines += [
            "    # TODO: supply real arguments",
            "    pytest.skip('not yet implemented')",
        ]

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "status": "created",
        "module": slug,
        "test_file": str(out.relative_to(root)),
        "tests_count": len(tools),
    }
