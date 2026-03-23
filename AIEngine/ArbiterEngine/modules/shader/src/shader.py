"""Shader module — GLSL/HLSL shader generation and validation."""
from __future__ import annotations
import shutil
import subprocess
from pathlib import Path
from core.logger import get_logger

logger = get_logger(__name__)

_GLSL_VERT_TEMPLATE = """\
#version 330 core
layout (location = 0) in vec3 aPos;
void main() {{
    gl_Position = vec4(aPos, 1.0);
}}
"""

_GLSL_FRAG_TEMPLATE = """\
#version 330 core
out vec4 FragColor;
void main() {{
    FragColor = vec4({r}, {g}, {b}, 1.0);
}}
"""

_HLSL_TEMPLATE = """\
struct VS_INPUT {{ float4 Pos : POSITION; }};
struct VS_OUTPUT {{ float4 Pos : SV_POSITION; }};
VS_OUTPUT VS(VS_INPUT input) {{
    VS_OUTPUT output;
    output.Pos = input.Pos;
    return output;
}}
float4 PS() : SV_TARGET {{
    return float4({r}, {g}, {b}, 1.0);
}}
"""


def compile_glsl(src: str, shader_type: str = "vert") -> dict:
    """Validate (and optionally compile) a GLSL shader using glslangValidator.

    The function validates the shader file and reports errors.  Compilation to
    machine code is handled by the GPU driver at runtime; this step catches
    GLSL syntax and semantic errors offline.
    """
    glslang = shutil.which("glslangValidator")
    if not glslang:
        return {"warning": "glslangValidator not found — shader not validated", "path": src}
    stage_flag = {"vert": "-S vert", "frag": "-S frag", "comp": "-S comp"}.get(shader_type, "")
    cmd = [glslang] + stage_flag.split() + [src]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "valid": result.returncode == 0,
    }


def compile_hlsl(src: str, entry: str = "VS", profile: str = "vs_5_0", dst: str | None = None) -> dict:
    """Compile HLSL using fxc.exe (Windows SDK)."""
    fxc = shutil.which("fxc")
    if not fxc:
        return {"warning": "fxc.exe not found — HLSL not compiled", "path": src}
    out = dst or Path(src).with_suffix(".cso")
    cmd = [fxc, "/T", profile, "/E", entry, "/Fo", str(out), src]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "output": str(out),
        "success": result.returncode == 0,
    }


def validate_shader(src: str) -> dict:
    """Validate a shader file based on its extension."""
    ext = Path(src).suffix.lower()
    if ext in {".vert", ".frag", ".geom", ".comp", ".glsl"}:
        return compile_glsl(src, shader_type=ext.lstrip("."))
    if ext in {".hlsl", ".fx"}:
        return compile_hlsl(src)
    return {"warning": f"Unknown shader extension: {ext}", "path": src}


def generate_spirv(src: str, dst: str | None = None) -> dict:
    """Generate SPIR-V bytecode from a GLSL shader using glslangValidator."""
    glslang = shutil.which("glslangValidator")
    if not glslang:
        return {"warning": "glslangValidator not found — SPIR-V not generated", "path": src}
    out = dst or str(Path(src).with_suffix(".spv"))
    cmd = [glslang, "-V", src, "-o", out]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "spirv": out,
        "success": result.returncode == 0,
    }


def generate_glsl_template(
    dst_vert: str,
    dst_frag: str,
    color: tuple[float, float, float] = (1.0, 0.5, 0.0),
) -> dict:
    """Write a minimal GLSL vertex+fragment shader pair."""
    r, g, b = color
    Path(dst_vert).parent.mkdir(parents=True, exist_ok=True)
    Path(dst_frag).parent.mkdir(parents=True, exist_ok=True)
    Path(dst_vert).write_text(_GLSL_VERT_TEMPLATE, encoding="utf-8")
    Path(dst_frag).write_text(_GLSL_FRAG_TEMPLATE.format(r=r, g=g, b=b), encoding="utf-8")
    return {"vert": dst_vert, "frag": dst_frag}


def generate_hlsl_template(dst: str, color: tuple[float, float, float] = (1.0, 0.5, 0.0)) -> dict:
    """Write a minimal HLSL shader file."""
    r, g, b = color
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    Path(dst).write_text(_HLSL_TEMPLATE.format(r=r, g=g, b=b), encoding="utf-8")
    return {"hlsl": dst}

