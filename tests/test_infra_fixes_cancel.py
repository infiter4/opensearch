"""Stop really stops: no in-flight model turn outlives a cancelled run, and no sandbox process
outlives its tool call — not on timeout, not on cancel."""
import asyncio
import os
from pathlib import Path

from backend.runtime import loop, report_tools
from backend.runtime.registry import AgentSpec
from backend.runtime.tools import Ctx, dispatch


def test_cancelling_the_run_task_cancels_the_in_flight_turn(monkeypatch):
    # research.stop() / sessions._gc / the orchestrator deadline all set the event AND cancel the
    # task; the task cancel lands first, inside _race_cancel's asyncio.wait.
    state = {"finished": 0, "cancelled": 0}

    def fake_chat(model, messages, **kw):
        async def gen():
            try:
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                state["cancelled"] += 1
                raise
            state["finished"] += 1
            yield {"type": "done", "content": "x", "thinking": "", "calls": [], "message": {}}
        return gen()

    monkeypatch.setattr(loop.llm, "chat", fake_chat)

    async def go():
        cancel = asyncio.Event()
        ctx = Ctx(agent="a", cancel=cancel)
        spec = AgentSpec(name="subagent", model="m", prompt="p", max_steps=3)

        async def pipeline():
            await asyncio.gather(*(loop.run_agent(spec, ctx, "q") for _ in range(4)))

        run = asyncio.create_task(pipeline())
        await asyncio.sleep(0.1)
        cancel.set()
        run.cancel()
        try:
            await run
        except BaseException:
            pass
        await asyncio.sleep(1.2)          # long enough for an orphan to have finished

    asyncio.run(go())
    assert state == {"finished": 0, "cancelled": 4}


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    stat = Path(f"/proc/{pid}/stat")      # a killed-but-unreaped zombie still answers kill(0)
    if stat.exists():
        try:
            return stat.read_text().rsplit(")", 1)[1].split()[0] != "Z"
        except (OSError, IndexError):
            return False
    return True


def _gone(pid: int, within: float = 3.0) -> bool:
    async def wait():
        for _ in range(int(within / 0.05)):
            if not _alive(pid):
                return True
            await asyncio.sleep(0.05)
        return not _alive(pid)
    return asyncio.run(wait())


def test_timeout_reaps_a_background_child_whose_shell_already_exited(monkeypatch, tmp_path):
    # `cmd & echo` exits the shell at once; the sleeper holds the pipe. The old early return on
    # `proc.returncode is not None` skipped exactly this tree.
    monkeypatch.setattr(report_tools, "RUN_TIMEOUT", 1.0)
    ctx = Ctx(agent="doer", workspace=str(tmp_path))
    out = asyncio.run(dispatch("run_shell", {"command": "sleep 30 & echo $! > bg.pid; echo started"}, ctx))
    assert "killed" in out
    pid = int((tmp_path / "bg.pid").read_text())
    assert _gone(pid), "background sleeper survived the timeout kill"


def test_cancel_kills_the_running_process_group(tmp_path):
    ctx = Ctx(agent="doer", workspace=str(tmp_path))
    pidfile = tmp_path / "bg.pid"

    async def go():
        t = asyncio.create_task(dispatch("run_shell", {"command": "sleep 30 & echo $! > bg.pid; wait"}, ctx))
        for _ in range(100):
            if pidfile.exists() and pidfile.read_text().strip():
                break
            await asyncio.sleep(0.02)
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass

    asyncio.run(go())
    pid = int(pidfile.read_text())
    assert _gone(pid), "a stopped run_shell left its process running"
