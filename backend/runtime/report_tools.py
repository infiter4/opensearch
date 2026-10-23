"""The reporter's hands: run code, run shell commands, write files, publish a document.

Scoped on purpose. A sandbox directory per run, a timeout per execution — enough to compute over
the verdict matrix, do light filesystem work (make a folder, move a file), and produce an
artifact. Every relative path is resolved and must stay inside the run's workspace; escapes are an
error the model sees, not an exception.

Portability: everything here is POSIX and works identically on macOS (BSD userland, zsh/sh) and
Linux. Two macOS-specific traps are handled deliberately:
  * Timeout kill reaps the whole *process group*, not just the direct child. `create_subprocess_*`
    with `start_new_session=True` puts the child in its own session; on timeout we SIGKILL the
    group so a shell's grandchildren (`mkdir & sleep 999 &`) die with it instead of orphaning.
  * The workspace guard uses `Path.is_relative_to`, not a hand-rolled string prefix with a
    hardcoded "/" separator.
Shell commands run through `/bin/sh -c`, which exists on both platforms — never `/bin/bash`
(macOS ships an ancient bash 3.2) and never GNU-only coreutils flags.
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
import uuid
from pathlib import Path

from .tools import Ctx, obj, tool

RUN_TIMEOUT = 30.0
MAX_OUT = 4000
MAX_FILE = 400_000


def _workspace(ctx: Ctx) -> Path:
    ws = getattr(ctx, "workspace", None)
    if not ws:
        raise RuntimeError("no workspace configured for this run")
    p = Path(ws)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _inside(ws: Path, name: str) -> Path:
    root = ws.resolve()
    p = (root / name).resolve()
    if p != root and not p.is_relative_to(root):
        raise ValueError(f"path escapes the workspace: {name}")
    return p


def _sandbox_env(ws: Path) -> dict[str, str]:
    """Just enough environment to run, and none of the server's credentials. Inheriting os.environ
    handed every child OLLAMA_API_KEY, TAVILY_API_KEY and the DB URL with its password — one `env`
    and they were in the tool output, the SSE stream and the committed cache.
    The interpreter's own bin dir leads PATH so `python3` in a shell is the venv (numpy/trimesh)."""
    bindir = str(Path(sys.executable).parent)
    return {
        "PATH": os.pathsep.join([bindir, os.environ.get("PATH") or os.defpath]),
        "HOME": str(ws.resolve()),
        "LANG": os.environ.get("LANG") or "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
    }


def _kill_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill the child and everything it spawned. POSIX process-group kill — macOS and Linux.

    Unconditional, by group id. `sleep 99 & echo ok` exits its shell at once, so the direct child
    already has a returncode while the sleeper it left behind holds the pipe — exactly the tree
    to reap. start_new_session made the child a group leader, so its pid IS the group id, and
    killpg still reaches the group after the leader itself is gone."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        # Group already gone, or we couldn't signal it — fall back to the direct child.
        try:
            proc.kill()
        except ProcessLookupError:
            pass


async def _execute(proc_factory, timeout: float) -> str:
    """Run a subprocess started in its own session, cap output, and reap the group on timeout."""
    proc = await proc_factory()
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        _kill_tree(proc)
        # Drain the pipe so the transport closes cleanly and we don't leak the reader task.
        try:
            await asyncio.wait_for(proc.communicate(), timeout=2.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            pass
        return f"ERROR: execution exceeded {timeout:.0f}s and was killed"
    except BaseException:
        # A stop cancels this coroutine mid-run. Without the kill the child outlived the run:
        # observed, a cancelled `sleep 42` still alive after the run reported "cancelled".
        _kill_tree(proc)
        raise
    text = out.decode(errors="replace")
    if len(text) > MAX_OUT:
        text = text[:MAX_OUT] + f"\n… truncated ({len(text)} chars total)"
    body = text if text.strip() else "(no output)"
    return f"exit={proc.returncode}\n{body}"


@tool(
    "run_python",
    "Execute a Python script in the run workspace and return its stdout/stderr. 30s limit. "
    "The standard library is available. Files you write persist in the workspace.",
    obj({"code": {"type": "string", "description": "Python source to execute"}}, ["code"]),
)
async def run_python(args: dict, ctx: Ctx) -> str:
    ws = _workspace(ctx)
    code = str(args.get("code") or "")
    return await _execute(
        lambda: asyncio.create_subprocess_exec(
            sys.executable, "-c", code,
            cwd=ws,
            env=_sandbox_env(ws),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        ),
        RUN_TIMEOUT,
    )


@tool(
    "run_shell",
    "Run a shell command in the run workspace and return its combined stdout/stderr. 30s limit. "
    "Runs under /bin/sh with the workspace as the working directory — good for light filesystem "
    "work like making a folder (mkdir -p), moving or listing files. Use portable POSIX commands "
    "(they run the same on macOS and Linux); avoid GNU-only flags. Relative paths stay in the "
    "sandbox.",
    obj({"command": {"type": "string", "description": "shell command, e.g. mkdir -p out && ls"}},
        ["command"]),
)
async def run_shell(args: dict, ctx: Ctx) -> str:
    ws = _workspace(ctx)
    command = str(args.get("command") or "").strip()
    if not command:
        return "ERROR: empty command"
    return await _execute(
        lambda: asyncio.create_subprocess_shell(
            command,
            cwd=ws,
            env=_sandbox_env(ws),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        ),
        RUN_TIMEOUT,
    )


@tool(
    "write_file",
    "Write a text file into the run workspace (relative path only).",
    obj({
        "path": {"type": "string", "description": "relative filename, e.g. data.csv"},
        "content": {"type": "string"},
    }, ["path", "content"]),
)
async def write_file(args: dict, ctx: Ctx) -> str:
    ws = _workspace(ctx)
    content = str(args.get("content") or "")
    if len(content) > MAX_FILE:
        return f"ERROR: content too large ({len(content)} > {MAX_FILE})"
    p = _inside(ws, str(args.get("path") or ""))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"wrote {p.name} ({len(content)} chars)"


_DOC_SHELL = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
  body {{ font: 15px/1.65 Georgia, 'Iowan Old Style', serif; color: #1c1917;
         max-width: 820px; margin: 2.5rem auto; padding: 0 1.5rem; }}
  h1, h2, h3 {{ line-height: 1.25; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13.5px; }}
  th, td {{ border: 1px solid #d6d3d1; padding: 6px 9px; text-align: left; }}
  th {{ background: #f5f5f4; }}
  code, pre {{ font: 12.5px/1.5 ui-monospace, monospace; background: #f5f5f4; }}
  pre {{ padding: 12px; overflow-x: auto; }}
  svg {{ max-width: 100%; height: auto; }}
  @media print {{ body {{ margin: 0.5in; max-width: none; }} }}
</style></head><body>
{body}
</body></html>
"""


@tool(
    "make_model",
    "Publish a 3D model file you wrote in the workspace (.glb preferred, or .stl/.gltf/.obj) as a "
    "viewable artifact — the user gets an interactive 3D viewer. Build the geometry first with "
    "run_python using `trimesh` (+ numpy): primitives via trimesh.creation.box/cylinder/..., "
    "boolean CSG via trimesh.boolean.union/difference, transforms via apply_translation, then "
    "mesh.export('part.glb'). Call this with that path.",
    obj({
        "path": {"type": "string", "description": "relative path to the model file, e.g. part.glb"},
        "title": {"type": "string"},
    }, ["path"]),
)
async def make_model(args: dict, ctx: Ctx) -> str:
    ws = _workspace(ctx)
    p = _inside(ws, str(args.get("path") or ""))
    ext = p.suffix.lower()
    if ext not in (".glb", ".gltf", ".stl", ".obj"):
        return f"ERROR: unsupported model format {ext!r}; write a .glb/.stl/.gltf/.obj first"
    if not p.exists():
        return f"ERROR: no such file {p.name} — write the model in the workspace before publishing"
    size = p.stat().st_size
    if size > MAX_FILE * 25:      # models are bigger than text; allow ~10MB
        return f"ERROR: model too large ({size} bytes)"

    art_id = uuid.uuid4().hex[:10]
    ctx.emit("artifact", {
        "id": art_id, "name": p.name, "kind": "model", "format": ext.lstrip("."),
        "bytes": size, "url": f"/api/artifact/{art_id}", "path": str(p),
    })
    return f"published 3D model {p.name} ({size} bytes) at /api/artifact/{art_id}"


@tool(
    "make_document",
    "Publish an HTML document as the run's report artifact. `body` is the inner HTML "
    "(headings, tables, inline SVG charts welcome — no external assets, they will not load). "
    "Returns the artifact URL shown to the user.",
    obj({
        "filename": {"type": "string", "description": "e.g. report.html"},
        "title": {"type": "string"},
        "body": {"type": "string", "description": "inner HTML of the document"},
    }, ["filename", "title", "body"]),
)
async def make_document(args: dict, ctx: Ctx) -> str:
    ws = _workspace(ctx)
    name = str(args.get("filename") or "report.html")
    if not name.endswith(".html"):
        name += ".html"
    p = _inside(ws, name)
    html = _DOC_SHELL.format(title=str(args.get("title") or "report"), body=str(args.get("body") or ""))
    if len(html) > MAX_FILE:
        return f"ERROR: document too large ({len(html)} chars)"
    p.write_text(html)

    art_id = uuid.uuid4().hex[:10]
    ctx.emit("artifact", {
        "id": art_id, "name": p.name, "kind": "report",
        "bytes": len(html), "url": f"/api/artifact/{art_id}",
        "path": str(p),
    })
    return f"published {p.name} at /api/artifact/{art_id}"
