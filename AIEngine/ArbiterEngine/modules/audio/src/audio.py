"""Audio module — audio file processing using stdlib and optional pydub."""
from __future__ import annotations
import shutil
import subprocess
from pathlib import Path
from core.logger import get_logger

logger = get_logger(__name__)


def _ffmpeg_run(cmd: list[str]) -> dict:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {"error": "ffmpeg not found on PATH"}
    result = subprocess.run([ffmpeg] + cmd, capture_output=True, text=True, timeout=120)
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
            "success": result.returncode == 0}


def audio_convert(src: str, dst: str, codec: str = "") -> dict:
    """Convert audio format using FFmpeg or pydub."""
    out = Path(dst)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["-y", "-i", src]
    if codec:
        cmd += ["-c:a", codec]
    cmd.append(str(out))
    result = _ffmpeg_run(cmd)
    if result.get("success"):
        return {"converted": str(out), "engine": "ffmpeg"}
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(src)
        audio.export(str(out), format=out.suffix.lstrip("."))
        return {"converted": str(out), "engine": "pydub"}
    except Exception as exc:
        return {"error": f"Audio conversion failed: {exc}", "src": src}


def audio_info(path: str) -> dict:
    """Return metadata about an audio file."""
    cmd = ["-v", "quiet", "-print_format", "json", "-show_streams", path]
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        result = subprocess.run(
            [ffprobe] + cmd, capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            import json as _json
            try:
                return _json.loads(result.stdout)
            except Exception:
                pass
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(path)
        return {
            "channels": audio.channels,
            "sample_rate": audio.frame_rate,
            "duration_ms": len(audio),
            "sample_width": audio.sample_width,
        }
    except Exception as exc:
        return {"error": str(exc), "path": path}


def audio_trim(src: str, dst: str, start_ms: int = 0, end_ms: int | None = None) -> dict:
    """Trim an audio file to the given time range."""
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(src)
        trimmed = audio[start_ms:end_ms]
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        trimmed.export(dst, format=Path(dst).suffix.lstrip("."))
        return {"trimmed": dst, "start_ms": start_ms, "end_ms": end_ms or len(audio)}
    except ImportError:
        pass
    # FFmpeg fallback
    ss = start_ms / 1000.0
    cmd = ["-y", "-ss", str(ss), "-i", src]
    if end_ms is not None:
        cmd += ["-t", str((end_ms - start_ms) / 1000.0)]
    cmd.append(dst)
    return _ffmpeg_run(cmd)


def audio_normalize(src: str, dst: str, target_db: float = -14.0) -> dict:
    """Normalize audio loudness using FFmpeg loudnorm filter."""
    cmd = ["-y", "-i", src, "-af", f"loudnorm=I={target_db}", dst]
    return _ffmpeg_run(cmd)


def audio_merge(inputs: list[str], dst: str) -> dict:
    """Merge (concatenate) multiple audio files into one."""
    try:
        from pydub import AudioSegment
        combined = AudioSegment.empty()
        for inp in inputs:
            combined += AudioSegment.from_file(inp)
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        combined.export(dst, format=Path(dst).suffix.lstrip("."))
        return {"merged": dst, "inputs": inputs}
    except ImportError:
        return {"error": "pydub not installed; cannot merge audio", "inputs": inputs}

