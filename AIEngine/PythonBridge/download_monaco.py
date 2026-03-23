"""download_monaco.py — Download Monaco Editor for offline-first operation.

Run once after setup to cache Monaco locally so the IDE never requires internet:

    python AIEngine/PythonBridge/download_monaco.py

The files are saved to ``AIEngine/PythonBridge/gui/vs/`` and served by the
FastAPI static mount at ``/gui/vs/``.  The IDE checks for a local copy first
(see index.html) and falls back to the CDN only when the local copy is absent.

Monaco version: 0.47.0  (~8 MB compressed)
"""
from __future__ import annotations

import sys
import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

MONACO_VERSION = "0.47.0"
CDN_BASE = f"https://cdn.jsdelivr.net/npm/monaco-editor@{MONACO_VERSION}/min/vs"
LOCAL_BASE = Path(__file__).resolve().parent / "gui" / "vs"

# Core files needed for the editor to start.
# The loader will request additional language files on demand; those are fetched
# from CDN at runtime if not present locally — which is fine for network setups.
REQUIRED_FILES = [
    "loader.js",
    "editor/editor.main.js",
    "editor/editor.main.css",
    "editor/editor.main.nls.js",
    "base/worker/workerMain.js",
]

# Language packs most useful for Arbiter (Python, JS/TS, C#, JSON, Markdown)
LANGUAGE_FILES = [
    "language/python/python.js",
    "language/javascript/javascript.js",
    "language/typescript/typescript.js",
    "language/typescript/typescriptWorker.js",
    "language/json/json.js",
    "language/json/jsonWorker.js",
    "language/markdown/markdown.js",
    "language/csharp/csharp.js",
    "language/html/html.js",
    "language/html/htmlWorker.js",
    "language/css/css.js",
    "language/css/cssWorker.js",
    "language/cpp/cpp.js",
    "language/rust/rust.js",
    "language/go/go.js",
    "language/shell/shell.js",
    "language/yaml/yaml.js",
    "language/xml/xml.js",
    "language/sql/sql.js",
]


def _download(rel_path: str, retries: int = 3) -> tuple[str, bool, str]:
    url = f"{CDN_BASE}/{rel_path}"
    dest = LOCAL_BASE / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                dest.write_bytes(resp.read())
            return rel_path, True, ""
        except Exception as exc:
            if attempt < retries - 1:
                time.sleep(1)
            else:
                return rel_path, False, str(exc)
    return rel_path, False, "max retries"


def main() -> int:
    print(f"Monaco Editor v{MONACO_VERSION} — offline installer")
    print(f"Destination: {LOCAL_BASE}")
    print()

    if LOCAL_BASE.exists() and any(LOCAL_BASE.rglob("loader.js")):
        ans = input("Monaco is already installed locally. Re-download? [y/N] ").strip().lower()
        if ans != "y":
            print("Skipped.")
            return 0

    all_files = REQUIRED_FILES + LANGUAGE_FILES
    ok = failed = 0

    print(f"Downloading {len(all_files)} files …\n")
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_download, f): f for f in all_files}
        for fut in as_completed(futures):
            rel, success, err = fut.result()
            if success:
                ok += 1
                print(f"  ✓  {rel}")
            else:
                failed += 1
                print(f"  ✗  {rel}  — {err}")

    print(f"\nDone: {ok} downloaded, {failed} failed.")
    if failed:
        print("Some files could not be downloaded.  The IDE will use CDN for missing files.")
    else:
        print("Monaco is now available offline.  Restart the backend to serve the local copy.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
