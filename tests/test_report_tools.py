"""The reporter's sandbox: three tools, one directory, no way out."""
import asyncio

import pytest

from backend.runtime import report_tools
from backend.runtime.tools import Ctx, dispatch


def _ctx(tmp_path, events):
    return Ctx(agent="reporter", emit=lambda e, d: events.append((e, d)), workspace=str(tmp_path))


def test_write_file_stays_inside_the_workspace(tmp_path):
    events = []
    out = asyncio.run(dispatch("write_file", {"path": "../escape.txt", "content": "x"}, _ctx(tmp_path, events)))
    assert out.startswith("ERROR"), out
    assert not (tmp_path.parent / "escape.txt").exists()

    out = asyncio.run(dispatch("write_file", {"path": "notes/data.csv", "content": "a,b"}, _ctx(tmp_path, events)))
    assert "wrote" in out
    assert (tmp_path / "notes/data.csv").read_text() == "a,b"


def test_run_python_executes_in_workspace(tmp_path):
    events = []
    out = asyncio.run(dispatch("run_python", {
        "code": "import pathlib; pathlib.Path('made.txt').write_text('hi'); print('done', 6*7)",
    }, _ctx(tmp_path, events)))
    assert "done 42" in out and "exit=0" in out
    assert (tmp_path / "made.txt").read_text() == "hi"


def test_run_python_reports_errors_as_information(tmp_path):
    out = asyncio.run(dispatch("run_python", {"code": "1/0"}, _ctx(tmp_path, [])))
    assert "ZeroDivisionError" in out and not out.startswith("ERROR:"), \
        "a traceback is model-actionable output, not a tool crash"


def test_make_document_publishes_and_emits_artifact(tmp_path):
    events = []
    out = asyncio.run(dispatch("make_document", {
        "filename": "report", "title": "Audit", "body": "<h1>Audit</h1><p>11/14 held up.</p>",
    }, _ctx(tmp_path, events)))
    assert "published report.html" in out

    arts = [d for e, d in events if e == "artifact"]
    assert len(arts) == 1
    a = arts[0]
    assert a["url"] == f"/api/artifact/{a['id']}"
    html = (tmp_path / "report.html").read_text()
    assert "11/14 held up." in html and "<!doctype html>" in html
    assert a["path"] == str(tmp_path / "report.html")


def test_no_workspace_is_a_hard_error(tmp_path):
    ctx = Ctx(agent="reporter", emit=lambda e, d: None, workspace=None)
    out = asyncio.run(dispatch("write_file", {"path": "x", "content": "y"}, ctx))
    assert out.startswith("ERROR")


@pytest.mark.slow
def test_run_python_timeout_kills(tmp_path):
    report_tools.RUN_TIMEOUT, saved = 1.0, report_tools.RUN_TIMEOUT
    try:
        out = asyncio.run(dispatch("run_python", {"code": "import time; time.sleep(5)"}, _ctx(tmp_path, [])))
        assert "killed" in out
    finally:
        report_tools.RUN_TIMEOUT = saved
