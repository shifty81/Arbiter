"""Script runner module — execute scripts in multiple languages."""
from __future__ import annotations
import subprocess
import sys


def _run(cmd: list[str], cwd: str | None = None, timeout: int = 60) -> dict:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    except FileNotFoundError:
        return {"returncode": -1, "stdout": "", "stderr": f"Executable not found: {cmd[0]}"}
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": f"Timeout after {timeout}s"}


def run_python(path: str, args: list[str] | None = None, cwd: str | None = None) -> dict:
    """Execute a Python script."""
    return _run([sys.executable, path] + (args or []), cwd=cwd)


def run_shell(path: str, args: list[str] | None = None, cwd: str | None = None) -> dict:
    """Execute a shell script (bash on Linux/macOS, cmd on Windows)."""
    import platform
    if platform.system() == "Windows":
        return _run(["cmd", "/c", path] + (args or []), cwd=cwd)
    return _run(["bash", path] + (args or []), cwd=cwd)


def run_powershell(path: str, args: list[str] | None = None, cwd: str | None = None) -> dict:
    """Execute a PowerShell script."""
    return _run(["powershell", "-ExecutionPolicy", "Bypass", "-File", path] + (args or []), cwd=cwd)


def run_lua(path: str, args: list[str] | None = None, cwd: str | None = None) -> dict:
    """Execute a Lua script."""
    return _run(["lua", path] + (args or []), cwd=cwd)


def run_node(path: str, args: list[str] | None = None, cwd: str | None = None) -> dict:
    """Execute a Node.js script."""
    return _run(["node", path] + (args or []), cwd=cwd)


def run_typescript(path: str, args: list[str] | None = None, cwd: str | None = None) -> dict:
    """Execute a TypeScript file via ts-node."""
    return _run(["ts-node", path] + (args or []), cwd=cwd)


def run_rust(path: str, args: list[str] | None = None, cwd: str | None = None) -> dict:
    """Compile and run a Rust file using rustc."""
    import os
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "out")
        compile_result = _run(["rustc", path, "-o", out])
        if compile_result["returncode"] != 0:
            return compile_result
        return _run([out] + (args or []), cwd=cwd)


def run_go(path: str, args: list[str] | None = None, cwd: str | None = None) -> dict:
    """Run a Go source file using 'go run'."""
    return _run(["go", "run", path] + (args or []), cwd=cwd)


def run_kotlin(path: str, args: list[str] | None = None, cwd: str | None = None) -> dict:
    """Compile and run a Kotlin script via kotlinc."""
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        jar = os.path.join(tmp, "out.jar")
        compile_result = _run(["kotlinc", path, "-include-runtime", "-d", jar])
        if compile_result["returncode"] != 0:
            return compile_result
        return _run(["java", "-jar", jar] + (args or []), cwd=cwd)


def run_java(path: str, args: list[str] | None = None, cwd: str | None = None) -> dict:
    """Compile and run a Java source file."""
    import os
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        compile_result = _run(["javac", "-d", tmp, path])
        if compile_result["returncode"] != 0:
            return compile_result
        class_name = Path(path).stem
        return _run(["java", "-cp", tmp, class_name] + (args or []), cwd=cwd)


def run_csharp_script(path: str, args: list[str] | None = None, cwd: str | None = None) -> dict:
    """Run a C# script using 'dotnet-script' or 'csi'."""
    import shutil
    if shutil.which("dotnet-script"):
        return _run(["dotnet-script", path] + (args or []), cwd=cwd)
    if shutil.which("csi"):
        return _run(["csi", path] + (args or []), cwd=cwd)
    return {"returncode": -1, "stdout": "", "stderr": "No C# script runner found (install dotnet-script or csi)."}


def eval_python(code: str) -> dict:
    """Evaluate Python code string in a sandboxed namespace."""
    import io
    from contextlib import redirect_stdout, redirect_stderr
    stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
    local_ns: dict = {}
    try:
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec(code, local_ns)  # noqa: S102
        return {"stdout": stdout_buf.getvalue(), "stderr": stderr_buf.getvalue(), "returncode": 0}
    except Exception as exc:
        return {"stdout": stdout_buf.getvalue(), "stderr": str(exc), "returncode": 1}
