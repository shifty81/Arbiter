"""Network module implementation."""
from __future__ import annotations
from pathlib import Path
import requests as _requests


def _req(method: str, url: str, **kwargs) -> dict:
    try:
        resp = _requests.request(method, url, timeout=kwargs.pop("timeout", 30), **kwargs)
        ct = resp.headers.get("content-type", "")
        body = resp.json() if "json" in ct else resp.text
        return {"status": resp.status_code, "body": body, "headers": dict(resp.headers)}
    except Exception as exc:
        return {"error": str(exc)}


def http_get(url: str, headers: dict | None = None, timeout: int = 30) -> dict:
    return _req("GET", url, headers=headers or {}, timeout=timeout)


def http_post(url: str, body: dict | None = None, headers: dict | None = None, timeout: int = 30) -> dict:
    return _req("POST", url, json=body or {}, headers=headers or {}, timeout=timeout)


def http_put(url: str, body: dict | None = None, headers: dict | None = None) -> dict:
    return _req("PUT", url, json=body or {}, headers=headers or {})


def http_delete(url: str, headers: dict | None = None) -> dict:
    return _req("DELETE", url, headers=headers or {})


def download_file(url: str, dst: str) -> dict:
    try:
        resp = _requests.get(url, stream=True, timeout=60)
        resp.raise_for_status()
        p = Path(dst)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("wb") as f:
            for chunk in resp.iter_content(65536):
                f.write(chunk)
        return {"downloaded": dst, "bytes": p.stat().st_size}
    except Exception as exc:
        return {"error": str(exc)}


def upload_file(url: str, path: str, headers: dict | None = None) -> dict:
    try:
        with open(path, "rb") as f:
            resp = _requests.post(url, data=f, headers=headers or {}, timeout=120)
        return {"status": resp.status_code, "body": resp.text}
    except Exception as exc:
        return {"error": str(exc)}
