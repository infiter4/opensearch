"""SSE framing."""
from __future__ import annotations

import json


def frame(event: str, data: dict) -> str:
    payload = json.dumps(data, default=str)
    # A literal newline inside data: would split the frame. json.dumps escapes them, but a
    # multi-line payload sneaking through would silently truncate the event client-side.
    return f"event: {event}\ndata: {payload}\n\n"


def comment(text: str = "") -> str:
    """Heartbeat. Proxies and browsers drop an idle event-stream; the verifier stage can be
    quiet for tens of seconds, which looks identical to a dead connection."""
    return f": {text}\n\n"
