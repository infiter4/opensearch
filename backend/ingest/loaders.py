"""Per-modality loaders: raw bytes -> Doc (extracted text the verifier will later quote-check).

Each modality returns the SAME Doc contract, so adding audio/CAD later is a new branch here and
nothing downstream changes. PDF keeps a page map so a chunk can cite 'p.4'.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

# extension -> (modality, lang)
_CODE = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "tsx", ".jsx": "jsx",
    ".go": "go", ".rs": "rust", ".java": "java", ".c": "c", ".h": "c", ".cpp": "cpp",
    ".cc": "cpp", ".hpp": "cpp", ".cs": "csharp", ".rb": "ruby", ".php": "php", ".swift": "swift",
    ".kt": "kotlin", ".scala": "scala", ".sh": "bash", ".sql": "sql", ".r": "r", ".m": "matlab",
    ".jl": "julia", ".lua": "lua", ".dart": "dart", ".vue": "vue",
}
_TEXT_EXT = {".txt", ".md", ".markdown", ".rst", ".org", ".text", ".csv", ".json", ".yaml", ".yml", ".toml"}


@dataclass
class Doc:
    modality: str            # text | code | pdf
    title: str
    text: str                # extracted text
    source_uri: str
    lang: str | None = None
    meta: dict = field(default_factory=dict)   # pdf: {"page_bounds": [end_offset_per_page]}


def _ext(name: str) -> str:
    i = name.rfind(".")
    return name[i:].lower() if i >= 0 else ""


def load(filename: str, data: bytes) -> Doc:
    """Dispatch on extension. Unknown text-like files are treated as plain text."""
    ext = _ext(filename)
    if ext == ".pdf":
        return _load_pdf(filename, data)
    if ext in _CODE:
        return Doc("code", filename, _decode(data), source_uri=filename, lang=_CODE[ext])
    # markdown/text/anything decodable
    return Doc("text", filename, _decode(data), source_uri=filename, lang=None)


def _decode(data: bytes) -> str:
    if isinstance(data, str):
        return data
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _load_pdf(filename: str, data: bytes) -> Doc:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    parts: list[str] = []
    page_bounds: list[int] = []       # cumulative end offset after each page -> maps char -> page
    cursor = 0
    for page in reader.pages:
        t = (page.extract_text() or "").strip()
        block = t + "\n\n"
        parts.append(block)
        cursor += len(block)
        page_bounds.append(cursor)
    text = "".join(parts)
    return Doc("pdf", filename, text, source_uri=filename, meta={"page_bounds": page_bounds})
