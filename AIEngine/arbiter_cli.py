#!/usr/bin/env python3
"""Arbiter CLI — command-line interface for the Arbiter platform.

Usage:
    arbiter build    [<project>] [--cmd <command>]
    arbiter run      [<project>] [--cmd <command>]
    arbiter test     [<project>] [--cmd <command>]
    arbiter chat     [<project>] <message>
    arbiter archive  list | rebuild | search <query>
    arbiter self-build status | next | start [--mode <mode>] [--task <task-id>]

Options:
    --server <url>     ArbiterEngine base URL (default: http://127.0.0.1:8001)
    --project <name>   Active project name (default: "default")
    --cmd <command>    Override the auto-detected build/run/test command
    --mode <mode>      Self-build autonomy mode: manual|assist|semiauto|fullauto
    --task <id>        Specific roadmap task to self-build (e.g. M5-1)

Environment variables:
    ARBITER_SERVER     Overrides --server
    ARBITER_PROJECT    Overrides --project

M8-5
"""
from __future__ import annotations

import json
import os
import sys
import argparse
import urllib.request
import urllib.parse
import urllib.error
from typing import Any


# ── Default configuration ─────────────────────────────────────────────────────

DEFAULT_SERVER  = os.environ.get("ARBITER_SERVER",  "http://127.0.0.1:8001")
DEFAULT_PROJECT = os.environ.get("ARBITER_PROJECT", "default")


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _get(server: str, path: str, params: dict | None = None) -> dict[str, Any]:
    """Send a GET request and return parsed JSON."""
    url = server.rstrip("/") + path
    if params:
        qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
        url = f"{url}?{qs}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as exc:
        _die(f"Could not reach Arbiter server at {server}: {exc}")


def _post(server: str, path: str, body: dict | None = None) -> dict[str, Any]:
    """Send a POST request with a JSON body and return parsed JSON."""
    url = server.rstrip("/") + path
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as exc:
        _die(f"Could not reach Arbiter server at {server}: {exc}")


def _die(msg: str) -> None:  # noqa: D401
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def _print_json(data: dict) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ── Sub-commands ──────────────────────────────────────────────────────────────

def cmd_build(args: argparse.Namespace) -> None:
    action = args.subcmd  # "build" | "run" | "test"
    result = _post(args.server, f"/{action}", {
        "project": args.project,
        "command": args.cmd or "",
    })
    print(result.get("output", ""))
    if not result.get("success", True):
        sys.exit(1)


def cmd_chat(args: argparse.Namespace) -> None:
    message = " ".join(args.message)
    if not message:
        _die("Please supply a message, e.g.:  arbiter chat 'How do I fix this bug?'")
    result = _post(args.server, "/chat", {
        "message": message,
        "project": args.project,
    })
    persona = result.get("persona", "Arbiter")
    print(f"[{persona}]\n{result.get('response', '')}")


def cmd_archive(args: argparse.Namespace) -> None:
    sub = args.archive_cmd
    if sub == "list":
        result = _get(args.server, "/archive")
        entries = result.get("entries", [])
        print(f"Archive: {len(entries)} entries")
        for e in entries[:20]:
            print(f"  {e['id'][:8]}  {e['language']:<12}  {e['title']}")
        if len(entries) > 20:
            print(f"  ... and {len(entries) - 20} more")
    elif sub == "rebuild":
        result = _post(args.server, "/archive/rebuild")
        print(f"Rebuild complete. Entries: {result.get('entries', '?')}")
    elif sub == "search":
        query = " ".join(args.query)
        if not query:
            _die("Usage: arbiter archive search <query>")
        result = _get(args.server, "/archive/search", {"q": query})
        hits = result.get("results", [])
        print(f"Search '{query}': {len(hits)} result(s)")
        for h in hits:
            print(f"  {h.get('title','')}\n    {h.get('content_snippet','')[:120]}")
    else:
        _die(f"Unknown archive subcommand: {sub}")


def cmd_self_build(args: argparse.Namespace) -> None:
    sub = args.sb_cmd
    if sub == "status":
        result = _get(args.server, "/self-build/status")
        print(f"Status: {result.get('status', 'unknown')}")
        if result.get("pending_approval"):
            print("  ⏳ Waiting for approval.  Use: arbiter self-build approve")
        print(f"Log lines: {result.get('log_lines', 0)}")
    elif sub == "next":
        result = _get(args.server, "/self-build/next")
        task = result.get("task")
        ms   = result.get("milestone")
        if task:
            print(f"Next task: [{task['id']}] {task.get('title','')}")
            if ms:
                print(f"Milestone: {ms.get('title','')}")
        else:
            print("All roadmap tasks complete! 🎉")
    elif sub == "start":
        result = _post(args.server, "/self-build/start", {
            "task_id": args.task or "",
            "mode": args.mode or "assist",
        })
        print(f"Started: {result.get('status','')} (mode={result.get('mode','')})")
        if result.get("mode") == "manual" and result.get("next_task"):
            t = result["next_task"]
            print(f"Next task: [{t['id']}] {t.get('title','')}")
    elif sub == "stop":
        result = _post(args.server, "/self-build/stop")
        print(f"Stopped: {result.get('status','')}")
    elif sub == "approve":
        result = _post(args.server, "/self-build/approve", {"approved": True})
        print(f"Approved: {result.get('status','')}")
    elif sub == "reject":
        result = _post(args.server, "/self-build/approve", {"approved": False})
        print(f"Rejected: {result.get('status','')}")
    elif sub == "log":
        result = _get(args.server, "/self-build/log", {"tail": args.tail or 50})
        for line in result.get("lines", []):
            print(line)
    else:
        _die(f"Unknown self-build subcommand: {sub}")


def cmd_health(args: argparse.Namespace) -> None:
    try:
        result = _get(args.server, "/health")
        print(f"Arbiter Engine: {result.get('status','?')} (v{result.get('version','?')})")
    except SystemExit:
        print("Arbiter Engine: offline")
        sys.exit(1)


def cmd_status(args: argparse.Namespace) -> None:
    result = _get(args.server, "/status")
    print(f"Backend:   {result.get('llm_backend','?')}")
    print(f"Tools:     {result.get('tool_count','?')}")
    print(f"CPU:       {result.get('cpu','?')}")
    print(f"RAM:       {result.get('ram_gb','?')} GB")
    print(f"GPU:       {result.get('gpu','?')}")


def cmd_review(args: argparse.Namespace) -> None:
    """M5-4: AI code review from the CLI."""
    path = args.file
    try:
        code = open(path, encoding="utf-8", errors="ignore").read()
    except OSError as exc:
        _die(str(exc))
    result = _post(args.server, "/ai/review", {
        "code": code,
        "file_path": path,
        "project": args.project,
    })
    print(f"Summary: {result.get('summary','')}")
    issues = result.get("issues", [])
    if issues:
        print(f"\nIssues ({len(issues)}):")
        for iss in issues:
            print(f"  Line {iss.get('line', 0):>4}  [{iss.get('severity','info'):<7}]  {iss.get('message','')}")
    else:
        print("No issues found.")


def cmd_diagram(args: argparse.Namespace) -> None:
    """M5-21: Generate a Mermaid diagram."""
    desc = " ".join(args.description)
    result = _post(args.server, "/ai/diagram", {
        "description": desc,
        "diagram_type": args.type or "flowchart",
        "project": args.project,
    })
    print(result.get("diagram", ""))


def cmd_deps_scan(args: argparse.Namespace) -> None:
    """M5-20: Dependency vulnerability scan."""
    result = _post(args.server, "/deps/scan", {"project": args.project})
    print(result.get("summary", ""))
    if result.get("error"):
        sys.exit(1)


# ── Argument parser ───────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arbiter",
        description="Arbiter CLI — AI-powered development platform",
    )
    parser.add_argument("--server",  default=DEFAULT_SERVER,  metavar="URL",
                        help=f"ArbiterEngine base URL (default: {DEFAULT_SERVER})")
    parser.add_argument("--project", default=DEFAULT_PROJECT, metavar="NAME",
                        help=f"Active project name (default: {DEFAULT_PROJECT})")

    sub = parser.add_subparsers(dest="subcmd", metavar="<command>")
    sub.required = True

    # build / run / test (share the same logic)
    for action in ("build", "run", "test"):
        p = sub.add_parser(action, help=f"{action.capitalize()} the project")
        p.add_argument("--cmd", default="", metavar="CMD",
                       help="Override the auto-detected command")
        p.set_defaults(handler=cmd_build)

    # chat
    p = sub.add_parser("chat", help="Send a message to the AI")
    p.add_argument("message", nargs=argparse.REMAINDER, help="Message text")
    p.set_defaults(handler=cmd_chat)

    # archive
    p = sub.add_parser("archive", help="Manage the code Archive")
    p.add_argument("archive_cmd", choices=["list", "rebuild", "search"],
                   metavar="list|rebuild|search")
    p.add_argument("query", nargs=argparse.REMAINDER, metavar="<terms>")
    p.set_defaults(handler=cmd_archive)

    # self-build
    p = sub.add_parser("self-build", help="Manage the autonomous self-build loop")
    p.add_argument("sb_cmd",
                   choices=["status", "next", "start", "stop", "approve", "reject", "log"],
                   metavar="status|next|start|stop|approve|reject|log")
    p.add_argument("--mode", default="assist",
                   choices=["manual", "assist", "semiauto", "fullauto"],
                   help="Autonomy mode for 'start'")
    p.add_argument("--task", default="", metavar="ID",
                   help="Specific roadmap task ID to build (e.g. M5-1)")
    p.add_argument("--tail", type=int, default=50,
                   help="Number of log lines to return for 'log'")
    p.set_defaults(handler=cmd_self_build)

    # review (M5-4)
    p = sub.add_parser("review", help="AI code review for a file (M5-4)")
    p.add_argument("file", metavar="FILE", help="Path to the file to review")
    p.set_defaults(handler=cmd_review)

    # diagram (M5-21)
    p = sub.add_parser("diagram", help="Generate a Mermaid diagram (M5-21)")
    p.add_argument("description", nargs=argparse.REMAINDER, help="Diagram description")
    p.add_argument("--type", default="flowchart",
                   choices=["flowchart", "sequence", "class", "er", "gantt", "pie"],
                   help="Diagram type")
    p.set_defaults(handler=cmd_diagram)

    # deps-scan (M5-20)
    p = sub.add_parser("deps-scan", help="Dependency vulnerability scan (M5-20)")
    p.set_defaults(handler=cmd_deps_scan)

    # health / status
    p = sub.add_parser("health", help="Check server health")
    p.set_defaults(handler=cmd_health)

    p = sub.add_parser("status", help="Show server and LLM status")
    p.set_defaults(handler=cmd_status)

    return parser


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
