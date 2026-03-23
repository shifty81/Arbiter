"""Image processing module implementation."""
from __future__ import annotations
from pathlib import Path

try:
    from PIL import Image
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


def _check():
    if not _HAS_PIL:
        raise RuntimeError("Pillow not installed")


def image_resize(path: str, width: int, height: int, dst: str | None = None) -> dict:
    _check()
    img = Image.open(path).resize((width, height), Image.LANCZOS)
    out = dst or path
    img.save(out)
    return {"resized": out, "size": [width, height]}


def image_convert(path: str, format: str, dst: str | None = None) -> dict:
    _check()
    img = Image.open(path)
    out = dst or (Path(path).stem + "." + format.lower())
    img.save(out, format=format.upper())
    return {"converted": out, "format": format}


def image_thumbnail(path: str, size: int, dst: str | None = None) -> dict:
    _check()
    img = Image.open(path)
    img.thumbnail((size, size), Image.LANCZOS)
    out = dst or path
    img.save(out)
    return {"thumbnail": out}


def image_crop(path: str, x: int, y: int, w: int, h: int, dst: str | None = None) -> dict:
    _check()
    img = Image.open(path).crop((x, y, x + w, y + h))
    out = dst or path
    img.save(out)
    return {"cropped": out, "box": [x, y, w, h]}


def image_flip(path: str, direction: str, dst: str | None = None) -> dict:
    _check()
    img = Image.open(path)
    flip_op = Image.FLIP_LEFT_RIGHT if direction == "horizontal" else Image.FLIP_TOP_BOTTOM
    img = img.transpose(flip_op)
    out = dst or path
    img.save(out)
    return {"flipped": out}


def image_rotate(path: str, degrees: float, dst: str | None = None) -> dict:
    _check()
    img = Image.open(path).rotate(degrees, expand=True)
    out = dst or path
    img.save(out)
    return {"rotated": out, "degrees": degrees}


def image_info(path: str) -> dict:
    """Return metadata about an image file."""
    _check()
    try:
        img = Image.open(path)
        return {
            "path": path,
            "format": img.format,
            "mode": img.mode,
            "width": img.width,
            "height": img.height,
            "size": [img.width, img.height],
            "size_bytes": Path(path).stat().st_size,
        }
    except Exception as exc:
        return {"error": str(exc)}


def batch_convert(src_dir: str, format: str, dst_dir: str) -> dict:
    _check()
    src, dst = Path(src_dir), Path(dst_dir)
    dst.mkdir(parents=True, exist_ok=True)
    exts = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".webp"}
    converted = []
    for p in src.iterdir():
        if p.suffix.lower() in exts:
            out = dst / (p.stem + "." + format.lower())
            Image.open(p).save(out, format=format.upper())
            converted.append(str(out))
    return {"converted": converted}
