"""The .env loader reads what a human writes — inline comments, quotes — and a mode it can't
recognise is said out loud and replaced, never silently run as `live`."""
import logging
import os

import pytest

from backend import config


@pytest.mark.parametrize("raw,want", [
    ("auto         # live | auto | replay", "auto"),
    ("            # required: chat models", ""),
    ('"quoted # not a comment"  # but this is', "quoted # not a comment"),
    ("'single'", "single"),
    ("pa#ss", "pa#ss"),                          # no whitespace before '#': part of the value
    ("plain", "plain"),
    ("", ""),
])
def test_env_value(raw, want):
    assert config._env_value(raw) == want


def test_load_env_strips_comments_and_quotes(monkeypatch, tmp_path):
    names = ("RCPT_T_MODE", "RCPT_T_EMPTY", "RCPT_T_QUOTED")
    for n in names:                              # register for restore, then make sure it's unset
        monkeypatch.setenv(n, "x")
        monkeypatch.delenv(n)
    env = tmp_path / ".env"
    env.write_text(
        "# a comment line\n"
        "RCPT_T_MODE=replay   # live | auto | replay\n"
        "RCPT_T_EMPTY=            # optional\n"
        'RCPT_T_QUOTED="v a l"\n'
    )
    config._load_env(env)
    assert os.environ["RCPT_T_MODE"] == "replay"
    assert os.environ["RCPT_T_EMPTY"] == ""
    assert os.environ["RCPT_T_QUOTED"] == "v a l"


def test_an_unknown_mode_warns_and_falls_back_to_auto(caplog):
    with caplog.at_level(logging.WARNING, logger="receipts"):
        assert config._research_mode("auto   # live | auto | replay") == "auto"
    assert "not one of live|auto|replay" in caplog.text
    for m in ("live", "auto", "replay"):
        assert config._research_mode(m) == m
