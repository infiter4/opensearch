-- Graph-RAG on Postgres. Idempotent. __EMBED_DIM__ is substituted from config.EMBED_DIM at
-- migrate time (the pgvector column dim is fixed at DDL — a one-way door, see config.py).
create extension if not exists vector;
create extension if not exists pg_trgm;

-- ---------- workspaces: the durable project boundary ----------
create table if not exists workspaces (
    id           uuid primary key default gen_random_uuid(),
    slug         text unique not null,
    title        text not null,
    owner_email  text,
    embed_model  text not null,            -- frozen at creation
    embed_dim    int  not null,            -- must equal the vector() column dim below
    created_at   timestamptz not null default now(),
    meta         jsonb not null default '{}'::jsonb
);

-- ---------- documents: one ingested artifact ----------
create table if not exists documents (
    id            uuid primary key default gen_random_uuid(),
    workspace_id  uuid not null references workspaces(id) on delete cascade,
    uri           text not null,           -- corpus://<slug>/<sha1>
    source_uri    text,                    -- original path/url
    modality      text not null,           -- text|code|pdf  (image|audio|cad later)
    title         text not null default '',
    content_sha1  text not null,
    n_chars       int  not null default 0,
    lang          text,
    created_at    timestamptz not null default now(),
    meta          jsonb not null default '{}'::jsonb,
    unique (workspace_id, content_sha1)     -- SourceRegistry dedup, in SQL
);

-- ---------- chunks: retrieval unit; body is what the verifier quote-checks ----------
create table if not exists chunks (
    id            uuid primary key default gen_random_uuid(),
    workspace_id  uuid not null references workspaces(id) on delete cascade,
    document_id   uuid not null references documents(id) on delete cascade,
    ordinal       int  not null,
    body          text not null,
    locator       text,                    -- 'p.4' | 'lines 30-58'
    char_start    int,
    char_end      int,
    token_count   int,
    embedding     vector(__EMBED_DIM__),
    tsv           tsvector generated always as (to_tsvector('english', coalesce(body,''))) stored,
    created_at    timestamptz not null default now(),
    meta          jsonb not null default '{}'::jsonb,
    unique (document_id, ordinal)
);

-- ---------- entities: graph nodes (concept.extract vocab) ----------
create table if not exists entities (
    id            uuid primary key default gen_random_uuid(),
    workspace_id  uuid not null references workspaces(id) on delete cascade,
    slug          text not null,
    label         text not null,
    type          text not null default 'concept',   -- root|entity|value|concept
    embedding     vector(__EMBED_DIM__),
    created_at    timestamptz not null default now(),
    meta          jsonb not null default '{}'::jsonb,
    unique (workspace_id, slug)
);

-- ---------- relations: directed labelled edges ----------
create table if not exists relations (
    id            uuid primary key default gen_random_uuid(),
    workspace_id  uuid not null references workspaces(id) on delete cascade,
    src_entity    uuid not null references entities(id) on delete cascade,
    dst_entity    uuid not null references entities(id) on delete cascade,
    label         text not null default '',
    weight        real not null default 1.0,
    document_id   uuid references documents(id) on delete set null,
    created_at    timestamptz not null default now(),
    unique (workspace_id, src_entity, dst_entity, label)
);

-- ---------- chunk_entities: graph <-> text bridge ----------
create table if not exists chunk_entities (
    chunk_id   uuid not null references chunks(id)   on delete cascade,
    entity_id  uuid not null references entities(id) on delete cascade,
    primary key (chunk_id, entity_id)
);

-- ---------- ingestions / runs: durable bookkeeping ----------
create table if not exists ingestions (
    id            uuid primary key default gen_random_uuid(),
    workspace_id  uuid not null references workspaces(id) on delete cascade,
    status        text not null default 'running',    -- running|done|error
    n_documents   int  not null default 0,
    n_chunks      int  not null default 0,
    started_at    timestamptz not null default now(),
    finished_at   timestamptz,
    error         text,
    meta          jsonb not null default '{}'::jsonb
);

create table if not exists runs (
    id            uuid primary key default gen_random_uuid(),
    workspace_id  uuid references workspaces(id) on delete set null,
    query_id      text not null,
    question      text not null,
    mode          text not null,
    answer_text   text,
    trust         jsonb,
    created_at    timestamptz not null default now(),
    meta          jsonb not null default '{}'::jsonb
);

-- ============================ indexes ============================
create index if not exists idx_chunks_embedding on chunks using hnsw (embedding vector_cosine_ops);
create index if not exists idx_chunks_tsv        on chunks using gin (tsv);
create index if not exists idx_chunks_body_trgm  on chunks using gin (body gin_trgm_ops);
create index if not exists idx_chunks_ws         on chunks(workspace_id);
create index if not exists idx_chunks_doc        on chunks(document_id);
create index if not exists idx_relations_ws_src  on relations(workspace_id, src_entity);
create index if not exists idx_relations_ws_dst  on relations(workspace_id, dst_entity);
create index if not exists idx_entities_ws_slug  on entities(workspace_id, slug);
create index if not exists idx_chunk_entities_ent on chunk_entities(entity_id);
create index if not exists idx_documents_ws_sha  on documents(workspace_id, content_sha1);
