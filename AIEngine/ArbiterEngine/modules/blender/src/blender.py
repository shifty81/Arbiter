"""Blender module — CLI-based Blender integration."""
from __future__ import annotations
import shutil
import subprocess
import tempfile
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)

_TIMEOUT = 120  # seconds


def _blender_exe() -> str:
    """Locate the Blender executable, returning an empty string if not found."""
    exe = shutil.which("blender")
    if exe:
        return exe
    candidates = [
        "/usr/bin/blender",
        "/usr/local/bin/blender",
        "/Applications/Blender.app/Contents/MacOS/Blender",
        "C:/Program Files/Blender Foundation/Blender 4.0/blender.exe",
        "C:/Program Files/Blender Foundation/Blender 3.6/blender.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return ""


def _run(cmd: list[str]) -> dict:
    """Run a subprocess command and return a standardised result dict."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT)
        return {
            "status": "ok" if proc.returncode == 0 else "error",
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
    except FileNotFoundError:
        return {"status": "error", "error": f"Executable not found: {cmd[0]}"}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Blender process timed out"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def blender_open(path: str, **kwargs) -> dict:
    """Open a .blend file with Blender (background mode verification)."""
    exe = _blender_exe()
    if not exe:
        return {"status": "error", "error": "Blender executable not found in PATH"}
    if not Path(path).exists():
        return {"status": "error", "error": f"File not found: {path}"}
    result = _run([exe, "--background", path, "--python-expr", "import bpy; print('opened:', bpy.data.filepath)"])
    result["path"] = path
    return result


def blender_render(blend_file: str, output: str = "/tmp/render####", frame: int = 1, **kwargs) -> dict:
    """Render a frame from a .blend file using the Blender CLI."""
    exe = _blender_exe()
    if not exe:
        return {"status": "error", "error": "Blender executable not found in PATH"}
    if not Path(blend_file).exists():
        return {"status": "error", "error": f"Blend file not found: {blend_file}"}
    Path(output).parent.mkdir(parents=True, exist_ok=True) if "#" not in output else None
    cmd = [exe, "--background", blend_file, "--render-output", output, "--render-frame", str(frame)]
    result = _run(cmd)
    result["blend_file"] = blend_file
    result["output"] = output
    result["frame"] = frame
    return result


def blender_export(blend_file: str, format: str, dst: str, **kwargs) -> dict:
    """Export a Blender scene to FBX, GLB, OBJ, or other formats via a Python script."""
    exe = _blender_exe()
    if not exe:
        return {"status": "error", "error": "Blender executable not found in PATH"}
    if not Path(blend_file).exists():
        return {"status": "error", "error": f"Blend file not found: {blend_file}"}

    fmt = format.upper()
    Path(dst).parent.mkdir(parents=True, exist_ok=True)

    export_scripts: dict[str, str] = {
        "FBX": (
            "import bpy\n"
            f"bpy.ops.export_scene.fbx(filepath=r'{dst}', use_selection=False)\n"
        ),
        "GLB": (
            "import bpy\n"
            f"bpy.ops.export_scene.gltf(filepath=r'{dst}', export_format='GLB')\n"
        ),
        "GLTF": (
            "import bpy\n"
            f"bpy.ops.export_scene.gltf(filepath=r'{dst}', export_format='GLTF_SEPARATE')\n"
        ),
        "OBJ": (
            "import bpy\n"
            f"bpy.ops.export_scene.obj(filepath=r'{dst}')\n"
        ),
        "STL": (
            "import bpy\n"
            f"bpy.ops.export_mesh.stl(filepath=r'{dst}')\n"
        ),
    }

    script_code = export_scripts.get(fmt)
    if not script_code:
        return {"status": "error", "error": f"Unsupported export format: {format}. Supported: FBX, GLB, GLTF, OBJ, STL"}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
        tmp.write(script_code)
        script_path = tmp.name

    try:
        result = _run([exe, "--background", blend_file, "--python", script_path])
    finally:
        Path(script_path).unlink(missing_ok=True)

    result["blend_file"] = blend_file
    result["format"] = fmt
    result["dst"] = dst
    return result


def blender_script(blend_file: str, script: str, **kwargs) -> dict:
    """Run an inline Python script inside Blender."""
    exe = _blender_exe()
    if not exe:
        return {"status": "error", "error": "Blender executable not found in PATH"}
    if not Path(blend_file).exists():
        return {"status": "error", "error": f"Blend file not found: {blend_file}"}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
        tmp.write(script)
        script_path = tmp.name

    try:
        result = _run([exe, "--background", blend_file, "--python", script_path])
    finally:
        Path(script_path).unlink(missing_ok=True)

    result["blend_file"] = blend_file
    return result


def blender_bake(blend_file: str, output_dir: str = "/tmp/bake", **kwargs) -> dict:
    """Bake textures in Blender and save them to *output_dir*."""
    exe = _blender_exe()
    if not exe:
        return {"status": "error", "error": "Blender executable not found in PATH"}
    if not Path(blend_file).exists():
        return {"status": "error", "error": f"Blend file not found: {blend_file}"}

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    bake_script = (
        "import bpy\n"
        f"bpy.context.scene.render.filepath = r'{output_dir}/'\n"
        "for obj in bpy.context.scene.objects:\n"
        "    if obj.type == 'MESH':\n"
        "        bpy.context.view_layer.objects.active = obj\n"
        "        bpy.ops.object.bake(type='DIFFUSE')\n"
        "print('bake complete')\n"
    )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
        tmp.write(bake_script)
        script_path = tmp.name

    try:
        result = _run([exe, "--background", blend_file, "--python", script_path])
    finally:
        Path(script_path).unlink(missing_ok=True)

    result["blend_file"] = blend_file
    result["output_dir"] = output_dir
    return result
