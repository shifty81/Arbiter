"""UI module — UI component code generation."""
from __future__ import annotations
import json
from pathlib import Path
from core.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Component templates
# ---------------------------------------------------------------------------
_IMGUI_BUTTON = """\
// ImGui button: {name}
if (ImGui::Button("{label}", ImVec2({w}, {h}))) {{
    // TODO: handle {name} click
}}
"""

_IMGUI_WINDOW = """\
// ImGui window: {name}
ImGui::Begin("{title}");
// TODO: add widgets here
ImGui::End();
"""

_HTML_BUTTON = """\
<button id="{id}" class="{cls}" onclick="{onclick}">{label}</button>
"""

_HTML_PANEL = """\
<div id="{id}" class="panel {cls}">
  <!-- TODO: add content here -->
</div>
"""


def ui_generate_component(
    component_type: str,
    name: str,
    framework: str = "imgui",
    options: dict | None = None,
) -> dict:
    """Generate UI component code.

    Parameters
    ----------
    component_type : str  ``"button"`` or ``"window"`` / ``"panel"``
    name : str  Component identifier
    framework : str  ``"imgui"`` (default), ``"html"``, or ``"win32"``
    options : dict  Extra options (label, width, height, class, onclick…)
    """
    opts = options or {}
    label = opts.get("label", name)
    code = ""
    if framework == "imgui":
        if component_type == "button":
            code = _IMGUI_BUTTON.format(
                name=name, label=label,
                w=opts.get("width", 120), h=opts.get("height", 30),
            )
        elif component_type in {"window", "panel"}:
            code = _IMGUI_WINDOW.format(name=name, title=opts.get("title", name))
    elif framework == "html":
        if component_type == "button":
            code = _HTML_BUTTON.format(
                id=name, cls=opts.get("class", "btn"),
                onclick=opts.get("onclick", ""), label=label,
            )
        elif component_type in {"window", "panel"}:
            code = _HTML_PANEL.format(
                id=name, cls=opts.get("class", ""),
            )
    if not code:
        code = f"// {framework} {component_type}: {name}\n// TODO: implement\n"
    return {"component": name, "framework": framework, "type": component_type, "code": code}


def ui_screenshot(element_id: str, output_path: str | None = None) -> dict:
    """Placeholder for UI element screenshots (requires running app)."""
    return {
        "note": "ui_screenshot requires a running application with screenshot support.",
        "element_id": element_id,
        "output_path": output_path,
    }


def ui_list_components() -> dict:
    """Return available component types per framework."""
    return {
        "imgui": ["button", "window", "checkbox", "slider", "text", "image"],
        "html": ["button", "panel", "input", "select", "table", "modal"],
        "win32": ["button", "edit", "listbox", "combobox", "dialog"],
    }


def ui_generate_layout(components: list[dict], output_path: str, framework: str = "imgui") -> dict:
    """Generate a source file containing multiple UI components."""
    snippets = []
    for comp in components:
        result = ui_generate_component(
            comp.get("type", "button"),
            comp.get("name", "widget"),
            framework=framework,
            options=comp.get("options"),
        )
        snippets.append(result["code"])
    joined = "\n".join(snippets)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(joined, encoding="utf-8")
    return {"layout": str(out), "component_count": len(components), "framework": framework}

