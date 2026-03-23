"""Animation module — keyframe data and BVH/JSON animation file I/O."""
from __future__ import annotations
import json
from pathlib import Path
from core.logger import get_logger

logger = get_logger(__name__)


def _ensure(p: str | Path) -> Path:
    path = Path(p)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def anim_import(path: str) -> dict:
    """Load animation data from a JSON or BVH file."""
    p = Path(path)
    if not p.exists():
        return {"error": f"File not found: {path}"}
    if p.suffix.lower() == ".json":
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return {"loaded": str(p), "frames": len(data.get("keyframes", [])), "data": data}
        except Exception as exc:
            return {"error": str(exc)}
    # Minimal BVH parse — return header only
    lines = p.read_text(encoding="utf-8").splitlines()
    frame_count = 0
    for line in lines:
        if line.strip().startswith("Frames:"):
            try:
                frame_count = int(line.split(":")[1].strip())
            except ValueError:
                pass
    return {"loaded": str(p), "format": "bvh", "frames": frame_count}


def anim_export(data: dict, path: str, fmt: str = "json") -> dict:
    """Export animation data to JSON."""
    out = _ensure(path)
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {"exported": str(out), "format": fmt}


def anim_bake(path: str, fps: int = 30) -> dict:
    """Bake animation curves at the given FPS (JSON format)."""
    p = Path(path)
    if not p.exists():
        return {"error": f"File not found: {path}"}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        keyframes = data.get("keyframes", [])
        baked = [kf for kf in keyframes if kf.get("frame", 0) % (60 // fps) == 0]
        baked_data = {**data, "keyframes": baked, "fps": fps}
        out_path = p.with_stem(p.stem + "_baked")
        out_path.write_text(json.dumps(baked_data, indent=2), encoding="utf-8")
        return {"baked": str(out_path), "frame_count": len(baked), "fps": fps}
    except Exception as exc:
        return {"error": str(exc)}


def anim_retarget(src_path: str, target_skeleton: dict, dst_path: str) -> dict:
    """Retarget animation keyframes to a new skeleton (stub — copies with mapping)."""
    p = Path(src_path)
    if not p.exists():
        return {"error": f"File not found: {src_path}"}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        # Apply skeleton mapping if provided
        mapping = target_skeleton.get("bone_map", {})
        for kf in data.get("keyframes", []):
            if "bones" in kf:
                kf["bones"] = {mapping.get(k, k): v for k, v in kf["bones"].items()}
        out = _ensure(dst_path)
        out.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return {"retargeted": str(out), "mapping_applied": bool(mapping)}
    except Exception as exc:
        return {"error": str(exc)}


def anim_create_template(path: str, bone_names: list[str], frame_count: int = 60) -> dict:
    """Create a blank animation template with specified bones."""
    out = _ensure(path)
    keyframes = [
        {"frame": i, "bones": {bone: {"rot": [0, 0, 0], "pos": [0, 0, 0]} for bone in bone_names}}
        for i in range(frame_count)
    ]
    data = {"bones": bone_names, "frame_count": frame_count, "fps": 30, "keyframes": keyframes}
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {"created": str(out), "bones": bone_names, "frames": frame_count}

