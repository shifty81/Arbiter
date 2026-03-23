"""Memory module — persistent key-value memory for the agent."""
from __future__ import annotations
import json
import time
from pathlib import Path


def _store_path(namespace: str) -> Path:
    p = Path("cache") / "memory" / f"{namespace}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load(namespace: str) -> dict:
    p = _store_path(namespace)
    return json.loads(p.read_text()) if p.exists() else {}


def _save(namespace: str, data: dict) -> None:
    _store_path(namespace).write_text(json.dumps(data, indent=2))


def memory_store(key: str, value: str, namespace: str = "default") -> dict:
    data = _load(namespace)
    data[key] = {"value": value, "timestamp": time.time()}
    _save(namespace, data)
    return {"stored": key, "namespace": namespace}


def memory_recall(key: str, namespace: str = "default") -> dict:
    entry = _load(namespace).get(key)
    if entry is None:
        return {"found": False, "value": None}
    return {"found": True, "value": entry["value"], "timestamp": entry["timestamp"]}


def memory_search(query: str, namespace: str = "default", limit: int = 10) -> dict:
    data = _load(namespace)
    q = query.lower()
    results = [
        {"key": k, "value": v["value"]}
        for k, v in data.items()
        if q in k.lower() or q in str(v["value"]).lower()
    ]
    return {"results": results[:limit], "count": len(results)}


def memory_delete(key: str, namespace: str = "default") -> dict:
    data = _load(namespace)
    existed = key in data
    data.pop(key, None)
    _save(namespace, data)
    return {"deleted": key, "existed": existed}


def memory_list(namespace: str = "default") -> dict:
    data = _load(namespace)
    return {"keys": list(data.keys()), "count": len(data)}
