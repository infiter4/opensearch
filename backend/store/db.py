"""asyncpg access to the Supabase Graph-RAG store.

ENTIRELY OPTIONAL. `is_enabled()` is False when SUPABASE_DB_URL is unset, and the heavy deps
(asyncpg, pgvector) are imported lazily inside the functions — a checkout with no DB never imports
them, so the existing web-research path keeps its exact dependency set.

Connection notes (see plan Risks): Supabase requires TLS (`ssl='require'`), and the session pooler
wants prepared statements off (`statement_cache_size=0`). Migrations may run against a DIRECT url
when the pooler rejects DDL.
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import config

_pool = None            # asyncpg.Pool | None
_migrated = False


def is_enabled() -> bool:
    return bool(config.SUPABASE_DB_URL)


def scrub(text: str) -> str:
    """Strip the password out of any DSN before it can reach a log or an SSE event."""
    return re.sub(r"(postgres[^:@\s]*):[^@\s]*@", r"\1:<redacted>@", text or "")


async def pool():
    """Lazily-created connection pool with the pgvector codec registered per connection."""
    global _pool
    if _pool is None:
        if not is_enabled():
            raise RuntimeError("store disabled: SUPABASE_DB_URL not set")
        import asyncpg
        from pgvector.asyncpg import register_vector

        async def _init(conn):
            await register_vector(conn)     # bind python list[float] <-> pgvector

        _pool = await asyncpg.create_pool(
            dsn=config.SUPABASE_DB_URL, ssl="require", statement_cache_size=0,
            min_size=1, max_size=8, init=_init,
        )
    return _pool


async def migrate() -> None:
    """Apply the schema once. Idempotent. Prefers the DIRECT url for DDL/`create extension`."""
    global _migrated
    if _migrated or not is_enabled():
        return
    import asyncpg

    sql = (Path(__file__).parent / "migrations" / "0001_init.sql").read_text()
    sql = sql.replace("__EMBED_DIM__", str(config.EMBED_DIM))
    dsn = config.SUPABASE_DB_DIRECT_URL or config.SUPABASE_DB_URL
    conn = await asyncpg.connect(dsn=dsn, ssl="require", statement_cache_size=0)
    try:
        await conn.execute(sql)
    finally:
        await conn.close()
    _migrated = True


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
