"""Optional Supabase-backed Graph-RAG store. Import-safe with no DB configured: is_enabled()
returns False and no heavy deps are imported until a store function is actually called."""
from __future__ import annotations

from .db import close, is_enabled, migrate, pool, scrub  # noqa: F401
