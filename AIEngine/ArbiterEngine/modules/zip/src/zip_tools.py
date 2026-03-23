"""Archive module implementation."""
from __future__ import annotations
import os
import shutil
import tarfile
import zipfile
from pathlib import Path


def zip_pack(src: str, dst: str) -> dict:
    base = dst.removesuffix(".zip")
    shutil.make_archive(base, "zip", src)
    return {"archive": dst}


def zip_extract(src: str, dst: str) -> dict:
    with zipfile.ZipFile(src) as z:
        z.extractall(dst)
    return {"extracted_to": dst}


def zip_add_file(archive: str, file: str) -> dict:
    with zipfile.ZipFile(archive, "a") as z:
        z.write(file, Path(file).name)
    return {"added": file, "to": archive}


def zip_remove_file(archive: str, file: str) -> dict:
    tmp = archive + ".tmp"
    with zipfile.ZipFile(archive) as zin, zipfile.ZipFile(tmp, "w") as zout:
        for item in zin.infolist():
            if item.filename != file:
                zout.writestr(item, zin.read(item.filename))
    os.replace(tmp, archive)
    return {"removed": file, "from": archive}


def tar_pack(src: str, dst: str, compression: str = "gz") -> dict:
    mode = f"w:{compression}" if compression else "w"
    with tarfile.open(dst, mode) as tf:
        tf.add(src, arcname=Path(src).name)
    return {"archive": dst}


def tar_extract(src: str, dst: str) -> dict:
    with tarfile.open(src) as tf:
        tf.extractall(dst)
    return {"extracted_to": dst}


def sevenz_pack(src: str, dst: str) -> dict:
    try:
        import py7zr
        with py7zr.SevenZipFile(dst, "w") as z:
            z.writeall(src, Path(src).name)
        return {"archive": dst}
    except ImportError:
        return {"error": "py7zr not installed"}


def sevenz_extract(src: str, dst: str) -> dict:
    try:
        import py7zr
        with py7zr.SevenZipFile(src) as z:
            z.extractall(dst)
        return {"extracted_to": dst}
    except ImportError:
        return {"error": "py7zr not installed"}
