#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIG = ROOT / "migration" / "upcc_v0_6_3"
DONOR = MIG / "donor"
MANIFEST = MIG / "DONOR_MANIFEST.json"
EXPECTED = MIG / "EXPECTED_RELEASE.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    if expected.get("version") != "0.6.3" or expected.get("build") != "B003R3":
        return fail("EXPECTED_RELEASE.json does not pin 0.6.3/B003R3")

    if not MANIFEST.exists():
        print("PENDING: physical B003R3 donor has not been imported yet.")
        print("Run scripts/Import-UpccDonor.ps1 with the actual full rollup or source directory.")
        return 2

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    if manifest.get("schema_version") != 1:
        return fail("unsupported donor manifest schema")
    if manifest.get("donor_id") != "upcc-0.6.3-B003R3":
        return fail("wrong donor_id")

    declared = manifest.get("files") or []
    if manifest.get("file_count") != len(declared):
        return fail("file_count does not match files array")

    actual_paths = sorted(p for p in DONOR.rglob("*") if p.is_file())
    if len(actual_paths) != len(declared):
        return fail(f"file count drift: manifest={len(declared)} actual={len(actual_paths)}")

    by_path = {entry["path"]: entry for entry in declared}
    errors: list[str] = []
    for path in actual_paths:
        rel = path.relative_to(DONOR).as_posix()
        entry = by_path.get(rel)
        if entry is None:
            errors.append(f"unmanifested file: {rel}")
            continue
        size = path.stat().st_size
        if size != entry.get("bytes"):
            errors.append(f"size mismatch: {rel}")
        digest = sha256(path)
        if digest != entry.get("sha256"):
            errors.append(f"sha256 mismatch: {rel}")

    for rel in sorted(set(by_path) - {p.relative_to(DONOR).as_posix() for p in actual_paths}):
        errors.append(f"manifest file missing: {rel}")

    if errors:
        for e in errors[:50]:
            print("FAIL:", e)
        if len(errors) > 50:
            print(f"... {len(errors)-50} additional error(s)")
        return 1

    print(f"PASS: immutable donor manifest verified ({len(actual_paths)} file(s)).")
    print("PASS: donor identity pinned to UPCC 0.6.3/B003R3.")
    print("NOTE: release-marker/content checks should be added after the physical donor tree is available and inspected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
