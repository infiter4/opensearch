"""The 'do-it' lane. When the router says a message is a TASK (not a research question), a single
agent with the computer-use tools performs it and returns an artifact — instead of planning,
searching, and fact-checking. Reuses the reporter's sandbox: one workspace per run, per-call
timeouts, no escape (see runtime/report_tools.py).
"""
from __future__ import annotations

from pathlib import Path

from .. import config
from ..runtime import report_tools  # noqa: F401 — import registers run_shell/run_python/write_file/make_document
from ..runtime.loop import run_agent
from ..runtime.registry import spec
from ..runtime.tools import Ctx

_TOOLS = ("run_shell", "run_python", "write_file", "make_document", "make_model")


def _context(history: list[dict] | None) -> str:
    if not history:
        return ""
    turns = "\n\n".join(
        f"Earlier question: {h.get('question', '')}\nAnswer given:\n{h.get('answer', '')}"
        for h in history[-3:] if h.get("answer")
    )
    if not turns:
        return ""
    return (
        "\n\nContext from this conversation — this is what \"this\", \"that\", \"the report\" or "
        f"\"the answer\" refers to. Act on it; do not research anything new:\n\n{turns}\n"
    )


async def run_task(question: str, query_id: str, emit, cancel, history=None) -> str:
    """Perform a CUA task. Emits agent_status/agent_token/agent_tool/artifact; returns a summary."""
    emit("agent_status", {"agent_id": "doer", "status": "spawned", "detail": question[:80]})
    ws = Path(config.DATA_DIR) / "artifacts" / query_id
    ctx = Ctx(agent="doer", emit=emit, cancel=cancel, workspace=str(ws))
    sp = spec("doer", tools=_TOOLS, max_steps=10, num_ctx=32768)

    prompt = (
        f"Task:\n{question}\n{_context(history)}\n"
        "Do the task now with your tools, then reply with a one-line summary of what you produced "
        "(include the artifact URL if you published one)."
    )
    emit("agent_status", {"agent_id": "doer", "status": "working"})
    try:
        out = await run_agent(sp, ctx, prompt)
    except Exception as e:
        emit("agent_status", {"agent_id": "doer", "status": "failed", "detail": str(e)[:160]})
        emit("error", {"scope": "doer", "message": f"{type(e).__name__}: {e}"})
        return f"The task could not be completed: {type(e).__name__}: {e}"
    emit("agent_status", {"agent_id": "doer", "status": "done"})
    return out
