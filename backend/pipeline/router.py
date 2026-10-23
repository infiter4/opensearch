"""Intent router: is this input a research QUESTION or a do-this-for-me TASK (CUA)?

Every input used to be force-fed into plan -> research -> verify, so "make this into a PDF" got
web-searched and fact-checked instead of done. This splits the two lanes up front.

Design (chosen: auto LLM router):
  * A keyword FAST-PATH resolves the confident majority in pure code. It also keeps the offline
    demo honest: the three demo questions all match the research pattern, so a `replay` run never
    makes a router model call it has no cache entry for.
  * Only genuinely AMBIGUOUS inputs reach the classifier model (one cheap JSON call).
  * If that call errors OR is a replay cache miss, we fall back to `research` — the historical,
    non-surprising default. Routing can misfire toward "do nothing surprising", never toward
    silently running a shell task the user didn't clearly ask for.
"""
from __future__ import annotations

import re

from ..providers import llm

VALID = ("research", "task")

# A genuine knowledge question. Checked FIRST so it beats a stray task verb: "how do I convert X
# to pdf" is research, not a request to convert anything. Deliberately ONLY true interrogatives —
# the polite request words (can/could/would/should/will you ...) are NOT here, because "could you
# make this a pdf" is a task, not a question. Those fall through to the task check / the model.
_RESEARCH = re.compile(
    r"^\s*(how|what|what'?s|which|who|whose|whom|when|where|why|is|are|was|were|do|does|did|"
    r"list|explain|compare|define|tell\s+me|research|summar(?:y|ize|ise))\b",
    re.I,
)

# A request to DO something to a file / folder / artifact — the CUA lane. `_FMT` is an output
# format; naming one after into/as/to/in ("...in a pdf form", "...into a csv") is a strong task
# signal a knowledge question almost never carries.
_FMT = r"(?:pdf|docx?|csv|xlsx?|html|markdown|zip|archive|spreadsheet|slides?|png|jpe?g|stl|glb|gltf|step|obj|3mf|scad)"
_TASK = re.compile(
    r"\b("
    r"(?:make|turn|convert|compile|save|export|render|format)\s+"
    r"(?:this|that|it|them|these|those|the\s+\w+|my\s+\w+)\b"
    r"|(?:make|create|generate|build|write|produce|save|export|render|compile|give\s+me)\s+"
    r"(?:me\s+)?(?:a|an|the)?\s*\w*\s*"
    r"(?:" + _FMT + r"|file|folder|directory|document|report|image|chart|diagram)\b"
    r"|(?:into|as|to|in)\s+(?:a\s+|an\s+)?(?:" + _FMT + r"|file|document|folder)\b"
    r"|(?:create|make)\s+(?:a\s+)?(?:folder|directory)\b"
    r"|mkdir\b|zip\s+up\b"
    r"|(?:rename|delete|remove|move|copy)\s+(?:the\s+)?(?:file|folder|directory|[\w./-]+\.\w+)\b"
    r"|3d\s*model\b|\bcad\s*(?:model|part|file|design)?\b"      # CAD / 3D intent
    r"|(?:export|save|render)\s+(?:it|this)?\s*(?:as|to|into)?\s*(?:an?\s+)?(?:" + _FMT + r")\b"
    r")",
    re.I,
)
# "design/build a … bracket" is a task, but the noun can sit several words after the verb
# ("design a parametric L-bracket"), so match verb-anywhere + CAD-noun-anywhere instead of adjacency.
_CAD_VERB = re.compile(r"\b(?:design|model|build|print|make|create|generate|fabricate)\b", re.I)
_CAD_NOUN = re.compile(
    r"\b(?:bracket|gear|mount|enclosure|flange|gasket|pulley|coupler|housing|standoff|spacer|"
    r"hinge|clip|part|knob|handle|adapter|jig|fixture|gizmo|widget|box|plate|cylinder|tube)\b",
    re.I,
)

# A task is something said TO the assistant: an imperative ("make this a pdf") or a polite request
# ("could you ..."). The patterns above match ANYWHERE, so on their own they also fired inside
# ordinary research questions that merely mention a format or a build verb — "best way to convert
# HTML to PDF in Python", "best CAD software", "median income in a zip code" all went to the shell
# agent. A task match now only counts when the message is addressed as a request; anything else is
# left to the model, whose own fallback is research.
_REQUEST = re.compile(
    r"^\s*(?:(?:ok(?:ay)?|great|perfect|thanks|thank\s+you|cool|nice|now|and|also|so|then|hey|hi)"
    r"\b[\s,!.]*)*"
    r"(?:please|pls|kindly|(?:can|could|would|will)\s+(?:you|u)|i\s+(?:want|need|would\s+like)\s+you\s+to"
    r"|go\s+ahead\s+and|help\s+me"
    r"|make|turn|convert|compile|save|export|render|format|create|generate|build|write|produce|give"
    r"|put|mkdir|zip|rename|delete|remove|move|copy|design|fabricate)\b",
    re.I,
)

_SYS = (
    "You are an intent router. Classify the user's message as exactly one of:\n"
    '- "research": a question best answered by finding and citing sources — facts, prices, '
    'comparisons, explanations, "how does X work".\n'
    '- "task": a request to DO something on the user\'s machine — create/convert/save a file, make '
    'a folder, turn a previous answer into a document or PDF, run a small script.\n\n'
    'Return ONLY JSON: {"kind":"research"|"task","title":"<=6 words","reason":"one short clause"}\n'
    'If you are genuinely unsure, choose "research".'
)


def _title(text: str) -> str:
    return " ".join((text or "").strip().split()[:8])[:60] or "task"


_MODES = ("lite", "pro", "deep")
_COMPARE = re.compile(r"\b(compare|versus|vs\.?|trade-?offs?|pros and cons|difference between)\b", re.I)
_DEEP = re.compile(r"\b(comprehensive|in[- ]depth|deep[- ]dive|exhaustive|survey|systematic|thorough)\b", re.I)


def complexity_mode(question: str) -> str:
    """Deterministic depth heuristic — no model, offline like fast_route. Simple lookups go lite;
    comparative/multi-part questions go pro; explicitly broad/analytical questions go deep."""
    t = (question or "").strip()
    if _DEEP.search(t):
        return "deep"       # an explicit request for breadth/depth
    words = len(t.split())
    signals = 0
    if words > 40:
        signals += 1
    if _COMPARE.search(t):
        signals += 1
    if len(re.findall(r"\?", t)) > 1 or re.search(r"\b(and|then|also|plus)\b.*\?", t):
        signals += 1     # multi-part
    if signals >= 3:
        return "deep"
    if signals >= 1:
        return "pro"
    return "lite"


def fast_route(text: str) -> str | None:
    """Deterministic, no model. Returns 'research' | 'task', or None when it can't be sure."""
    t = (text or "").strip()
    if not t:
        return None
    if _RESEARCH.match(t):
        return "research"
    if not _REQUEST.match(t):
        return None     # mentions a format or a build verb, but is not asking us to DO anything
    if _TASK.search(t):
        return "task"
    # "design a parametric L-bracket with holes" — a build verb plus a physical/CAD noun anywhere.
    if _CAD_VERB.search(t) and _CAD_NOUN.search(t):
        return "task"
    return None


def _mode_for(question: str, corpus_available: bool) -> str:
    m = complexity_mode(question)
    # A real corpus rewards at least pro (hybrid retrieval + rerank pay off over a single reader).
    if corpus_available and m == "lite":
        m = "pro"
    return m


async def classify(question: str, history: list[dict] | None = None,
                   corpus_available: bool = False) -> dict:
    """{kind, title, reason, via, mode}. `mode` is the auto-selected depth (lite|pro|deep); the
    orchestrator only uses it when the incoming mode is "auto". `via` is fast|model|default."""
    mode = _mode_for(question, corpus_available)
    fast = fast_route(question)
    if fast:
        return {"kind": fast, "title": _title(question), "reason": "matched a clear pattern",
                "via": "fast", "mode": mode}

    prior = ""
    if history:
        last = next((h for h in reversed(history) if h.get("answer")), None)
        if last:
            prior = f'\n\n(For reference, "this"/"that" may mean the previous answer about: ' \
                    f'{str(last.get("question") or "")[:120]})'
    try:
        raw = await llm.complete_json(
            llm.model_for("router"),   # the run's BYOK pick, like every other stage
            [{"role": "system", "content": _SYS},
             {"role": "user", "content": f"Message: {question}{prior}"}],
            num_ctx=4096, temperature=0.0,
        )
    except Exception:
        raw = None

    if isinstance(raw, dict) and raw.get("kind") in VALID:
        return {"kind": raw["kind"], "title": str(raw.get("title") or _title(question))[:60],
                "reason": str(raw.get("reason") or "")[:120], "via": "model", "mode": mode}
    # Unclassifiable, model failure, or a replay cache miss -> the historical default.
    return {"kind": "research", "title": _title(question), "reason": "defaulted to research",
            "via": "default", "mode": mode}
