"""Hardware profiler — detects RAM, VRAM, and CPU for adaptive AI configuration.

Provides cross-platform detection with no mandatory additional dependencies.
Uses ``psutil`` when installed for more accurate readings; falls back to
platform-specific OS commands otherwise.

Public API
----------
detect_hardware() -> HardwareProfile
    Detect RAM, VRAM, CPU counts, and GPU name.

suggest_model_config(model_path, profile) -> dict
    Return optimal ``n_gpu_layers``, ``n_ctx``, and ``n_threads`` for a GGUF
    model file on the detected hardware, with human-readable rationale.
"""
from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.logger import get_logger

logger = get_logger(__name__)

_BYTES_PER_GIB: int = 1_073_741_824


# ── Hardware profile dataclass ────────────────────────────────────────────────

@dataclass
class HardwareProfile:
    """Snapshot of the host machine's AI-relevant hardware resources."""

    # System RAM (GiB)
    ram_total_gb: float = 0.0
    ram_available_gb: float = 0.0

    # GPU VRAM (GiB); 0 if no GPU detected or on Apple unified-memory
    vram_total_gb: float = 0.0
    vram_free_gb: float = 0.0

    # CPU
    cpu_cores_physical: int = 1
    cpu_cores_logical: int = 1

    # Informational
    gpu_name: str = ""
    platform_name: str = ""
    detection_method: str = ""   # "psutil" | "system_commands" | "partial"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ram_total_gb":       self.ram_total_gb,
            "ram_available_gb":   self.ram_available_gb,
            "vram_total_gb":      self.vram_total_gb,
            "vram_free_gb":       self.vram_free_gb,
            "cpu_cores_physical": self.cpu_cores_physical,
            "cpu_cores_logical":  self.cpu_cores_logical,
            "gpu_name":           self.gpu_name,
            "platform":           self.platform_name,
            "detection_method":   self.detection_method,
        }


# ── RAM detection ─────────────────────────────────────────────────────────────

def _ram_bytes() -> tuple[int, int]:
    """Return (total_bytes, available_bytes). Best-effort across platforms."""
    # psutil — most accurate and portable
    try:
        import psutil  # type: ignore[import]
        vm = psutil.virtual_memory()
        return int(vm.total), int(vm.available)
    except ImportError:
        pass

    plat = platform.system()

    if plat == "Linux":
        try:
            info: dict[str, int] = {}
            with open("/proc/meminfo", encoding="ascii") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        info[parts[0].rstrip(":")] = int(parts[1]) * 1024
            return info.get("MemTotal", 0), info.get("MemAvailable", 0)
        except Exception as exc:
            logger.debug("Linux /proc/meminfo read failed: %s", exc)

    elif plat == "Darwin":
        try:
            out = subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"], timeout=5
            ).decode().strip()
            total = int(out)
            # Available: read vm_stat
            vm_out = subprocess.check_output(
                ["vm_stat"], timeout=5
            ).decode()
            pages_free = 0
            for line in vm_out.splitlines():
                if "Pages free" in line:
                    pages_free = int(line.split(":")[1].strip().rstrip("."))
                    break
            page_size_out = subprocess.check_output(
                ["pagesize"], timeout=5
            ).decode().strip()
            is_numeric = page_size_out.isdigit()
            if not is_numeric:
                logger.warning(
                    "macOS pagesize command returned unexpected output %r — "
                    "falling back to 4096 bytes", page_size_out
                )
            page_size = int(page_size_out) if is_numeric else 4096
            return total, pages_free * page_size
        except Exception as exc:
            logger.debug("macOS sysctl RAM detection failed: %s", exc)

    elif plat == "Windows":
        try:
            out = subprocess.check_output(
                [
                    "wmic", "OS", "get",
                    "TotalVisibleMemorySize,FreePhysicalMemory",
                    "/Format:csv",
                ],
                timeout=10,
                stderr=subprocess.DEVNULL,
            ).decode()
            for line in out.splitlines():
                parts = [p.strip() for p in line.split(",")]
                # CSV: Node,FreePhysicalMemory,TotalVisibleMemorySize
                if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
                    free_kb  = int(parts[1])
                    total_kb = int(parts[2])
                    return total_kb * 1024, free_kb * 1024
        except Exception as exc:
            logger.debug("Windows wmic RAM detection failed: %s", exc)

    return 0, 0


# ── VRAM detection ────────────────────────────────────────────────────────────

def _vram_bytes() -> tuple[int, int, str]:
    """Return (total_bytes, free_bytes, gpu_name). Best-effort."""
    # NVIDIA via nvidia-smi
    try:
        raw = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=memory.total,memory.free,name",
                "--format=csv,noheader,nounits",
            ],
            timeout=8,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        if raw:
            # Take first GPU if multiple
            first_line = raw.splitlines()[0]
            parts = [p.strip() for p in first_line.split(",")]
            if len(parts) >= 3:
                total = int(parts[0]) * 1_048_576   # MiB → bytes
                free  = int(parts[1]) * 1_048_576
                name  = parts[2]
                return total, free, name
    except FileNotFoundError:
        pass   # nvidia-smi not present — not an NVIDIA system
    except Exception as exc:
        logger.debug("nvidia-smi VRAM detection failed: %s", exc)

    # Apple Silicon — unified memory; report a fraction of system RAM
    if platform.system() == "Darwin":
        try:
            chip_out = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                timeout=5,
                stderr=subprocess.DEVNULL,
            ).decode().strip()
            if "Apple" in chip_out or chip_out == "":
                # Detect Apple Silicon via hw.optional.arm64
                arm_out = subprocess.check_output(
                    ["sysctl", "-n", "hw.optional.arm64"],
                    timeout=5,
                    stderr=subprocess.DEVNULL,
                ).decode().strip()
                if arm_out == "1":
                    total_b, avail_b = _ram_bytes()
                    # Conventionally report ~60% of total RAM as usable unified GPU memory
                    gpu_share = int(total_b * 0.60)
                    return gpu_share, int(avail_b * 0.60), "Apple Silicon (unified memory)"
        except Exception as exc:
            logger.debug("Apple Silicon VRAM estimation failed: %s", exc)

    return 0, 0, ""


# ── CPU detection ─────────────────────────────────────────────────────────────

def _cpu_cores() -> tuple[int, int]:
    """Return (physical_cores, logical_cores)."""
    logical = os.cpu_count() or 1

    try:
        import psutil  # type: ignore[import]
        physical = psutil.cpu_count(logical=False) or 1
        return physical, logical
    except ImportError:
        pass

    # Estimate: assume hyperthreading (2 logical per physical)
    physical = max(1, logical // 2)
    return physical, logical


# ── Public API ────────────────────────────────────────────────────────────────

def detect_hardware() -> HardwareProfile:
    """Detect the host machine's AI-relevant hardware resources.

    Returns a ``HardwareProfile`` with RAM, VRAM, CPU, and GPU information.
    Never raises — returns zeros for any values that cannot be determined.
    """
    ram_total, ram_avail   = _ram_bytes()
    vram_total, vram_free, gpu_name = _vram_bytes()
    cpu_phys, cpu_logi     = _cpu_cores()

    try:
        import psutil  # type: ignore[import]
        method = "psutil"
    except ImportError:
        method = "system_commands"

    profile = HardwareProfile(
        ram_total_gb       = round(ram_total  / _BYTES_PER_GIB, 2),
        ram_available_gb   = round(ram_avail  / _BYTES_PER_GIB, 2),
        vram_total_gb      = round(vram_total / _BYTES_PER_GIB, 2),
        vram_free_gb       = round(vram_free  / _BYTES_PER_GIB, 2),
        cpu_cores_physical = cpu_phys,
        cpu_cores_logical  = cpu_logi,
        gpu_name           = gpu_name,
        platform_name      = platform.system(),
        detection_method   = method,
    )
    logger.info(
        "Hardware profile: RAM %.1f GiB (%.1f free)  VRAM %.1f GiB (%.1f free)  "
        "CPU %d physical / %d logical  GPU: %s",
        profile.ram_total_gb, profile.ram_available_gb,
        profile.vram_total_gb, profile.vram_free_gb,
        profile.cpu_cores_physical, profile.cpu_cores_logical,
        profile.gpu_name or "none",
    )
    return profile


def _model_size_gb(model_path: str) -> float:
    """Return the .gguf file size in GiB, or 0.0 if not accessible."""
    try:
        return Path(model_path).stat().st_size / _BYTES_PER_GIB
    except Exception:
        return 0.0


def suggest_model_config(
    model_path: str,
    profile: HardwareProfile,
) -> dict[str, Any]:
    """Suggest optimal llama-cpp-python load parameters for the given hardware.

    Calculates ``n_gpu_layers``, ``n_ctx``, and ``n_threads`` by comparing
    the model's file size against available VRAM and RAM, then choosing
    values that maximise performance without exceeding memory budgets.

    Parameters
    ----------
    model_path
        Path to the ``.gguf`` file.  Used to determine the model's disk size
        as a proxy for its memory footprint.
    profile
        Hardware profile as returned by :func:`detect_hardware`.

    Returns
    -------
    dict with keys:
        ``n_gpu_layers``  — int; -1 = full GPU, 0 = CPU-only, N = partial
        ``n_ctx``         — int; recommended context-window size in tokens
        ``n_threads``     — int; recommended CPU inference threads
        ``fits_in_vram``  — bool; whether the model fits entirely in VRAM
        ``rationale``     — list[str]; human-readable explanation of choices
    """
    size_gb  = _model_size_gb(model_path)
    rationale: list[str] = []

    # ── n_gpu_layers ─────────────────────────────────────────────────────────
    # Reserve ~18% of VRAM for OS/driver/KV-cache overhead.
    usable_vram = profile.vram_total_gb * 0.82

    if profile.vram_total_gb <= 0:
        n_gpu_layers = 0
        fits_in_vram = False
        rationale.append(
            "No GPU VRAM detected — CPU-only inference (n_gpu_layers=0). "
            "Install CUDA drivers or use an Apple Silicon Mac for GPU acceleration."
        )
    elif size_gb <= 0:
        # Model file size unknown: full GPU if we have decent VRAM, else CPU
        if usable_vram >= 4:
            n_gpu_layers = -1
            fits_in_vram = True
            rationale.append(
                f"Model size unknown; sufficient VRAM ({profile.vram_total_gb:.1f} GiB "
                f"detected) — defaulting to full GPU offload (n_gpu_layers=-1)."
            )
        else:
            n_gpu_layers = 0
            fits_in_vram = False
            rationale.append(
                f"Model size unknown and VRAM is limited ({profile.vram_total_gb:.1f} GiB) "
                "— defaulting to CPU inference (n_gpu_layers=0)."
            )
    elif size_gb <= usable_vram:
        n_gpu_layers = -1
        fits_in_vram = True
        rationale.append(
            f"Model ({size_gb:.1f} GiB) fits within usable VRAM "
            f"({usable_vram:.1f} GiB of {profile.vram_total_gb:.1f} GiB total) "
            "— full GPU offload (n_gpu_layers=-1). Expect fastest inference."
        )
    else:
        fits_in_vram = False
        # Partial GPU offload: estimate number of transformer layers from file size.
        # Rough heuristic (Q4_K_M quantisation):
        #   7B  model → ~32 layers / ~4.1 GiB  ≈ 7.8 layers/GiB
        #   13B model → ~40 layers / ~7.4 GiB  ≈ 5.4 layers/GiB
        #   30B model → ~60 layers / ~17  GiB  ≈ 3.5 layers/GiB
        # Conservative estimate: 6 layers/GiB
        est_layers    = max(1, int(size_gb * 6))
        offload_frac  = usable_vram / size_gb
        n_gpu_layers  = max(1, int(est_layers * offload_frac))
        rationale.append(
            f"Model ({size_gb:.1f} GiB) exceeds usable VRAM "
            f"({usable_vram:.1f} GiB of {profile.vram_total_gb:.1f} GiB total). "
            f"Partial GPU offload: ~{n_gpu_layers} of ~{est_layers} estimated layers "
            "on GPU. Remaining layers run on CPU."
        )

    # ── n_ctx ─────────────────────────────────────────────────────────────────
    # KV-cache memory scales with context length.  More RAM → bigger window.
    if profile.ram_total_gb >= 32:
        n_ctx = 8192
        rationale.append(
            f"{profile.ram_total_gb:.0f} GiB RAM detected — using large context "
            f"window ({n_ctx} tokens). Suitable for long conversations and large "
            "code files."
        )
    elif profile.ram_total_gb >= 16:
        n_ctx = 4096
        rationale.append(
            f"{profile.ram_total_gb:.0f} GiB RAM — standard context window "
            f"({n_ctx} tokens)."
        )
    elif profile.ram_total_gb >= 8:
        n_ctx = 2048
        rationale.append(
            f"{profile.ram_total_gb:.0f} GiB RAM — reduced context window "
            f"({n_ctx} tokens) to keep memory usage manageable."
        )
    else:
        n_ctx = 1024
        rationale.append(
            f"{profile.ram_total_gb:.0f} GiB RAM — minimal context window "
            f"({n_ctx} tokens). Consider upgrading RAM for better AI performance."
        )

    # ── n_threads ─────────────────────────────────────────────────────────────
    # For full GPU inference very few CPU threads are needed (just for the
    # non-offloaded layers and tokenisation).  For CPU/partial inference,
    # use all physical cores.
    if n_gpu_layers == -1:
        n_threads = max(1, min(4, profile.cpu_cores_physical))
        rationale.append(
            f"Full GPU inference — minimal CPU threads ({n_threads}). "
            "The GPU handles all computation."
        )
    else:
        n_threads = max(1, profile.cpu_cores_physical)
        rationale.append(
            f"CPU/partial inference — using {n_threads} physical CPU "
            f"core(s) of {profile.cpu_cores_logical} logical for best throughput."
        )

    return {
        "n_gpu_layers": n_gpu_layers,
        "n_ctx":        n_ctx,
        "n_threads":    n_threads,
        "fits_in_vram": fits_in_vram,
        "rationale":    rationale,
    }
