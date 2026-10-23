"""Workspace CRUD. A workspace is the durable project boundary that owns documents, chunks, and
the entity/relation graph. embed_model/embed_dim are frozen at creation (dim is a one-way door)."""
from __future__ import annotations

import re

from . import db


def slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return (s or "workspace")[:48]


async def create_workspace(title: str, embed_model: str, embed_dim: int,
                           owner_email: str | None = None) -> dict:
    p = await db.pool()
    base = slugify(title)
    async with p.acquire() as c:
        slug, n = base, 1
        while await c.fetchval("select 1 from workspaces where slug=$1", slug):
            n += 1
            slug = f"{base}-{n}"
        row = await c.fetchrow(
            "insert into workspaces(slug, title, owner_email, embed_model, embed_dim) "
            "values($1,$2,$3,$4,$5) "
            "returning id, slug, title, owner_email, embed_model, embed_dim, created_at",
            slug, title, owner_email, embed_model, embed_dim,
        )
    return dict(row)


async def get_by_slug(slug: str) -> dict | None:
    p = await db.pool()
    async with p.acquire() as c:
        row = await c.fetchrow(
            "select id, slug, title, owner_email, embed_model, embed_dim, created_at "
            "from workspaces where slug=$1", slug,
        )
    return dict(row) if row else None


async def delete_workspace(slug: str) -> bool:
    """Delete a workspace and everything it owns (documents/chunks/entities cascade)."""
    p = await db.pool()
    async with p.acquire() as c:
        res = await c.execute("delete from workspaces where slug=$1", slug)
    return not res.endswith(" 0")   # asyncpg returns "DELETE <n>"


async def list_workspaces() -> list[dict]:
    p = await db.pool()
    async with p.acquire() as c:
        rows = await c.fetch(
            "select w.id, w.slug, w.title, w.embed_model, w.embed_dim, w.created_at, "
            "  (select count(*) from documents d where d.workspace_id = w.id) as n_documents, "
            "  (select count(*) from chunks ch where ch.workspace_id = w.id) as n_chunks "
            "from workspaces w order by w.created_at desc",
        )
    return [dict(r) for r in rows]
