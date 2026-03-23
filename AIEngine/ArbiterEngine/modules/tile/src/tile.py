"""Tile module — tileset slicing, packing, and tilemap I/O."""
from __future__ import annotations
import json
from pathlib import Path
from core.logger import get_logger

logger = get_logger(__name__)


def _check_pil() -> None:
    try:
        import PIL  # noqa: F401
    except ImportError:
        raise RuntimeError("Pillow is required for tile operations. Install with: pip install Pillow")


def tile_slice(src: str, tile_w: int, tile_h: int, dst_dir: str) -> dict:
    """Slice a tileset image into individual tile images."""
    _check_pil()
    from PIL import Image
    img = Image.open(src)
    w, h = img.size
    Path(dst_dir).mkdir(parents=True, exist_ok=True)
    tiles: list[str] = []
    idx = 0
    for row in range(0, h, tile_h):
        for col in range(0, w, tile_w):
            tile = img.crop((col, row, col + tile_w, row + tile_h))
            out = str(Path(dst_dir) / f"tile_{idx:04d}.png")
            tile.save(out)
            tiles.append(out)
            idx += 1
    return {"sliced": len(tiles), "tiles": tiles, "tile_size": [tile_w, tile_h]}


def tile_pack(src_dir: str, tile_w: int, tile_h: int, dst: str, columns: int = 16) -> dict:
    """Pack individual tile images into a single tileset atlas."""
    _check_pil()
    from PIL import Image
    tile_files = sorted(Path(src_dir).glob("*.png"))
    if not tile_files:
        return {"error": f"No PNG files found in {src_dir}"}
    rows = (len(tile_files) + columns - 1) // columns
    atlas = Image.new("RGBA", (columns * tile_w, rows * tile_h), (0, 0, 0, 0))
    for idx, tf in enumerate(tile_files):
        tile = Image.open(tf).resize((tile_w, tile_h))
        col = idx % columns
        row = idx // columns
        atlas.paste(tile, (col * tile_w, row * tile_h))
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    atlas.save(dst)
    return {"packed": dst, "tiles": len(tile_files), "atlas_size": list(atlas.size)}


def tile_export(tilemap: dict, dst: str) -> dict:
    """Export a tilemap dictionary to a JSON file."""
    out = Path(dst)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(tilemap, indent=2), encoding="utf-8")
    return {"exported": str(out)}


def tile_create_map(
    width: int,
    height: int,
    default_tile: int = 0,
    dst: str | None = None,
) -> dict:
    """Create a blank tilemap of given dimensions."""
    tilemap = {
        "width": width,
        "height": height,
        "layers": [
            {
                "name": "ground",
                "data": [default_tile] * (width * height),
            }
        ],
    }
    if dst:
        tile_export(tilemap, dst)
    return {"tilemap": tilemap, "cells": width * height}

