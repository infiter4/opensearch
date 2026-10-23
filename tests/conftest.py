"""Every test gets its own cache file.

data/cache.sqlite is the record/replay store. A test that forgot to redirect the cache recorded
into it — RESEARCH_MODE=live still WRITES each successful turn — and a fake `"hi" -> "hi"` turn
landed in the real store. Hermetic by default, so no test can do that again.
"""
import pytest

from backend import config
from backend.providers import cache


@pytest.fixture(autouse=True)
def _private_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite")
    monkeypatch.setattr(cache, "_conn", None)
