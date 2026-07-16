"""SSE framing."""
from __future__ import annotations

import json


def frame(event: str, data: dict, eid: int | None = None) -> str:
    payload = json.dumps(data, default=str)
    # A literal newline inside data: would split the frame. json.dumps escapes them, but a
    # multi-line payload sneaking through would silently truncate the event client-side.
    #
    # `id:` is not decoration. EventSource remembers the last id it saw and sends it back as
    # Last-Event-ID when it silently reconnects, which is what lets a dropped stream resume from
    # where it stopped instead of restarting the whole run.
    head = f"id: {eid}\n" if eid is not None else ""
    return f"{head}event: {event}\ndata: {payload}\n\n"


def comment(text: str = "") -> str:
    """Heartbeat. Proxies and browsers drop an idle event-stream; the verifier stage can be
    quiet for tens of seconds, which looks identical to a dead connection."""
    return f": {text}\n\n"
