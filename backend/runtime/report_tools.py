"""The reporter's hands: run code, write files, publish a document. Deep mode only.

Scoped hard on purpose. Three tools, one sandbox directory per run, 30s per execution — enough to
compute over the verdict matrix and produce an artifact, not enough to become a general shell.
Every path is resolved and must stay inside the run's workspace; escapes are an error the model
sees, not an exception.
"""
from __future__ import annotations

import asyncio
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
    p = (ws / name).resolve()
    if not str(p).startswith(str(ws.resolve()) + "/") and p != ws.resolve():
        raise ValueError(f"path escapes the workspace: {name}")
    return p


@tool(
    "run_python",
    "Execute a Python script in the run workspace and return its stdout/stderr. 30s limit. "
    "The standard library is available. Files you write persist in the workspace.",
    obj({"code": {"type": "string", "description": "Python source to execute"}}, ["code"]),
)
async def run_python(args: dict, ctx: Ctx) -> str:
    ws = _workspace(ctx)
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", str(args.get("code") or ""),
        cwd=ws,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=RUN_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        return f"ERROR: execution exceeded {RUN_TIMEOUT:.0f}s and was killed"
    text = out.decode(errors="replace")
    if len(text) > MAX_OUT:
        text = text[:MAX_OUT] + f"\n… truncated ({len(text)} chars total)"
    return f"exit={proc.returncode}\n{text}" if text.strip() else f"exit={proc.returncode} (no output)"


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
