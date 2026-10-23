# receipts

**Everyone else cites. This verifies.**

A research chat that decomposes your question, researches the parts in parallel, and then checks
**every claim it wrote against the actual text of the source it cited** — using a *different model
that never sees the question or the answer*. Claims that fail get rewritten against the real
evidence, or honestly retracted. Then it shows you the work.

The documented failure of AI search is **citation infidelity**: confidently citing a source that
doesn't support the claim. This catches it, repairs it, and shows you what didn't survive.

It now does this across **three lanes**, chosen automatically per input:

- **Task** — "make this into a PDF", "create a folder" → a computer-use agent *does it* and returns a file.
- **Web research** — the classic verify-everything pipeline over the open web.
- **Corpus research** — the same pipeline over **your own ingested documents** (text, code, PDFs), backed by a persistent Graph-RAG store.

---

## Table of contents

1. [Run it](#run-it)
2. [How one input flows (the router)](#how-one-input-flows-the-router)
3. [The research pipeline](#the-research-pipeline)
4. [The five things that make it real](#the-five-things-that-make-it-real)
5. [Workspaces: multimodal Graph-RAG](#workspaces-multimodal-graph-rag)
6. [The intent router](#the-intent-router)
7. [Computer use (the terminal / doer)](#computer-use-the-terminal--doer)
8. [Models — three families, and that's the point](#models--three-families-and-thats-the-point)
9. [Search & depth modes](#search--depth-modes)
10. [The cache is the demo](#the-cache-is-the-demo)
11. [Persistence & the feature flag](#persistence--the-feature-flag)
12. [Configuration](#configuration)
13. [Architecture map](#architecture-map)
14. [Tests](#tests)
15. [Security](#security)
16. [Roadmap](#roadmap)

---

## Run it

**Prerequisites**

- Python 3.11+, Node 20+.
- A local **Ollama daemon** for embeddings (`ollama serve`) with an embed model pulled:
  `ollama pull embeddinggemma` (768-dim). Ollama Cloud gates `/api/embed` on the free tier, so
  embeddings run locally — this also means your corpus embeds offline.
- Optional: a **Postgres with `pgvector`** (e.g. Supabase) to enable workspaces. Without it, the
  app runs web-only, exactly as before.

**Backend + frontend**

```bash
cp .env.example .env          # fill in keys; see Configuration below
python -m venv .venv
.venv/bin/pip install httpx fastapi uvicorn pytest \
    asyncpg pgvector pypdf python-multipart      # last four only needed for workspaces
.venv/bin/uvicorn backend.main:app --port 8000 --reload   # terminal 1
cd web && npm install && npm run dev                       # terminal 2 -> localhost:5173
```

**No browser needed to debug** — every stage streams as JSON from the CLI:

```bash
.venv/bin/python -m backend.pipeline.orchestrator "your question" --mode pro --quiet
# add --jsonl for full untruncated machine-readable output
```

---

## How one input flows (the router)

Every message hits an **intent router** first. It classifies the input and picks a depth, then
sends it down one of three lanes:

```
input
 └─ router.classify()  ──────────────┬── kind = task ───────▶  DOER lane  (computer use)
     · research vs task              │                          run_shell / run_python /
     · auto depth: lite|pro|deep     │                          write_file / make_document  → artifact
                                     │
                                     └── kind = research ───▶  RESEARCH pipeline
                                          │
                              workspace bound?  ─ no ─▶  WEB lane      (web_search / read_page)
                                          │
                                          └─ yes ────▶  CORPUS lane   (corpus_search / corpus_read
                                                                        over your ingested documents)
```

The router is **code-first**: a keyword fast-path resolves the confident majority with no model
call (so the offline demo never depends on it), falling back to a small JSON model call only for
genuinely ambiguous inputs — and defaulting to `research` if that call fails. Depth (`lite`/`pro`/
`deep`) is chosen by a deterministic complexity heuristic when you ask in `auto` mode.

---

## The research pipeline

Both the web lane and the corpus lane run the **same** verify-everything pipeline. The only
difference is the two tools the sub-agents hold.

```
question
  ├─ planner            -> N independent subqueries, each tagged with a search lane
  │                        (deep mode adds a RED TEAM agent hunting disconfirming evidence)
  ├─ N sub-agents in parallel (asyncio.gather), each with its own tool loop:
  │     web lane:     web_search  -> Ollama + Tavily + OpenAlex fired together, fused with RRF
  │                   read_page   -> Ollama fetch -> Jina Reader fallback -> drop
  │     corpus lane:  corpus_search -> dense (pgvector) + keyword (tsvector), fused with RRF
  │                   corpus_read   -> read one ingested passage
  │     every source read is interned into the SourceRegistry
  │  -> draft with LOCAL [1..n] citations
  ├─ renumber   local -> global, IN CODE. invented markers dropped, never guessed
  ├─ segment    exact char offsets. no model.
  ├─ claims     atomic claims from CITED sentences only
  ├─ verify     verify_pair(claim, source_text) per (claim, cited source)
  ├─ rewrite    failing sentences repaired against real evidence, or RETRACTed. cap in code.
  ├─ lead       merges the sub-answers — with no search tools and no source bodies
  ├─ verify     THE LEAD TOO, against text it never saw — then the SAME repair pipeline
  └─ deep mode  provenance graph (pure code) + reporter agent -> HTML audit report
```

**Row identity is permanent.** Sentence ids are assigned once, at first segmentation, and only
ever carried forward (`segment.respan`). A retracted sentence keeps its row as a zero-width span:
the board strikes it through instead of letting the grid resolve clean by deleting its own
failures. *A grid that resolves clean by deleting its own failures is a lie.*

---

## The five things that make it real

**1. The verifier cannot grade its own homework.**
`verify_pair(claim_text: str, source_text: str) -> Verdict` takes exactly two strings. There is no
parameter for the question, the answer, sibling claims, or other sources. Context leakage is
structurally impossible without changing the signature — not a prompt discipline someone has to
remember. It runs on a **different model family** from the writer.

**2. The verifier cannot fake support.**
It must return a quote it claims is in the source. The server then looks for that quote with
`str.find()` (after unicode folding). If it isn't literally there and the verdict was `supported`,
the server **downgrades it to `weak`**. Support is checked by string search, not by a model's say-so.

**3. Citation numbers never touch a model.**
Each sub-agent cites small local numbers (`[1]`, `[2]`) — the regime models are reliable in. A
`SourceRegistry` allocates global ids at retrieval time and pure, unit-tested code remaps them.
Invented markers (a source the agent never opened) are dropped and surfaced, never guessed.

**4. `RETRACT` is the mechanism, not the fallback.**
A model with no legal way to say "I can't support this" will invent something. Making retraction a
first-class, explicitly-praised output is what converts a hallucination generator into an honest
one. Failed claims surface in **"What we could not establish"** — derived from real verification
failures. The rewrite loop's iteration cap is a `range()`, not a request; hitting it auto-retracts.

**5. The merge is a second surface, so it's verified too.**
The lead sees only source *identity* (id, url, title) — never a source body, no search tools — then
its own answer is put through the exact same verify → rewrite → retract pipeline, checked against
text it never read.

---

## Workspaces: multimodal Graph-RAG

A **workspace** is a durable project that holds your ingested material and everything researched
over it. Point a run at a workspace and it researches **your documents** instead of the web — with
every sentence fact-checked against **your own text** by the same blind verifier.

This is a **two-phase** design: **ingest**, then **research**.

### Phase 1 — Ingestion

```
upload text/code/pdf
  └─ loaders.load        per-modality: text/markdown, code (line locators), PDF (pypdf + page map)
    └─ chunk_text        ~512-token windows with overlap; exact char offsets + a human locator
                         ("p.4" for PDFs, "lines 30-58" for code) so a citation can be highlighted
      └─ llm.embeddings  local `embeddinggemma`, 768-dim, batched, cached/replayable
        └─ upsert        documents (sha1-deduped) + chunks (embedding + tsvector) in Postgres
```

### Phase 2 — Retrieval (non-naive RAG)

`corpus_search` embeds the query and runs two lanes concurrently, fused by the **same Reciprocal
Rank Fusion** the web path uses:

- **dense** — pgvector cosine ANN over chunk embeddings (`embedding <=> query`, HNSW index).
- **keyword** — Postgres full-text (`tsvector` / `ts_rank_cd`).

A chunk found by both lanes floats up carrying both — the same cross-lane corroboration signal the
web path gets for free. `corpus_read` then reads a passage and **interns it into the run's
`SourceRegistry`**.

### The seam that makes this cheap

Because `corpus_read` interns chunks into the **same `SourceRegistry`** as `read_page`, and because
`verify_pair` takes any two strings, **renumber, segment, claims, verify, rewrite, and lead-merge
run byte-for-byte unchanged** — now fact-checking against your documents. Citations resolve through
the same `/api/source/{id}` drawer, which highlights the supporting quote inside the ingested
passage. *No changes to the verifier.*

### The store (Postgres + pgvector)

The "graph" in Graph-RAG is implemented relationally (portable to managed Postgres, which supports
`pgvector` but not Apache AGE):

| table | holds |
|---|---|
| `workspaces` | one project; freezes its `embed_model` + `embed_dim` at creation |
| `documents` | one ingested artifact; `unique(workspace, content_sha1)` = dedup in SQL |
| `chunks` | the retrieval unit: `body`, `locator`, char offsets, `embedding vector(768)`, generated `tsvector` |
| `entities` / `relations` | graph nodes + directed labelled edges (populated by the deferred graph lane) |
| `chunk_entities` | bridges the graph back to the text it came from |
| `ingestions` / `runs` | durable bookkeeping |

Indexes: HNSW (vector), GIN (tsvector + trigram), btree on scoping columns. Graph traversal (a
later milestone) walks `relations` with a recursive CTE and hops back to text via `chunk_entities`.

### Auto depth

In `auto` mode a deterministic heuristic picks the depth: simple lookups → `lite`, comparative or
multi-part → `pro`, explicitly broad/analytical ("comprehensive", "in-depth survey") → `deep`. A
real corpus nudges a trivial question up to `pro` (hybrid retrieval pays off).

---

## The intent router

`router.classify(question)` returns `{kind, mode, title, reason, via}`:

- **`kind`** — `research` or `task`. Fast-path first: a knowledge-question pattern (`how/what/which/
  is/do…`) beats a stray task verb, so *"how do I convert markdown to pdf"* is research, while
  *"could you make this a pdf"* is a task. Only genuinely ambiguous inputs reach the model.
- **`mode`** — the auto-selected depth (used only when you asked in `auto`).
- **`via`** — `fast | model | default`, surfaced so you can see how it decided.

Misrouting fails safe: anything the code can't classify, and any model failure or offline
cache-miss, defaults to `research`.

---

## Computer use (the terminal / doer)

Task inputs go to the **doer** — a single agent with a sandboxed toolset (one workspace directory
per run, per-call timeouts, no path escape):

| tool | does |
|---|---|
| `run_shell` | run a POSIX shell command (`mkdir -p out`, move/list files) |
| `run_python` | run a Python script (stdlib + `numpy` / `trimesh` for geometry) |
| `write_file` | write a text file into the sandbox |
| `make_document` | publish a self-contained HTML document as a downloadable artifact (print-to-PDF) |
| `make_model` | publish a **3D model** (`.glb`/`.stl`) built with `trimesh` — the user gets an interactive in-app viewer |

**3D / CAD.** "design an L-bracket", "make a 3D model of a phone stand", "export it as an STL" route
to the doer, which builds real geometry with **trimesh** (primitives + boolean CSG + transforms),
exports a **GLB**, and publishes it via `make_model`. The frontend renders it in a lazy-loaded
three.js viewer (drag to orbit, scroll to zoom, download). This is *mesh* CAD; true parametric
B-rep (STEP, fillets) is still on the roadmap.

**Cross-platform by construction.** Commands run under `/bin/sh` (never `/bin/bash` — macOS ships
an ancient one) with portable POSIX only, so they behave identically on macOS (BSD userland) and
Linux. On timeout the whole **process group** is reaped (`start_new_session` + `killpg`), so a
shell's backgrounded children die instead of orphaning; the sandbox guard uses `Path.is_relative_to`
rather than a hand-rolled separator check. The deep-mode reporter uses the same tools to compile
its audit report.

---

## Models — three families, and that's the point

| stage | model | why |
|---|---|---|
| planner / claims / **verifier** / router | `kimi-k2.6:cloud` | JSON reliability; **different family from the writer** |
| **sub-agent / lead** | `minimax-m3:cloud` | the writer |
| **rewriter** | `qwen3.5:397b:cloud` | **third family** — the repair is judged by neither writer nor verifier |
| reporter / doer | `kimi-k2.7-code:cloud` | strong tool use |
| embedder | `embeddinggemma` (local) | 768-dim, offline; Ollama Cloud gates `/api/embed` |

The rule: **minimax writes → kimi verifies → qwen repairs.** Never let the rewriter share a family
with the verifier, or the fix gets graded by its own author. **BYOK** is wired per run: any stage
can be routed to `groq/…`, `openrouter/…`, or `google/…` via an OpenAI-compat adapter, with keys
supplied inline. Per-run models and keys live in `ContextVars`, so two concurrent runs can never
see each other's models — or keys.

**Transport doctrine:** the httpx timeout is a *per-read stall budget* (a healthy stream resets it
every chunk), not a total cap. A single 429 parks every caller on a shared cooldown instead of each
retrying into the same wall.

---

## Search & depth modes

| mode | agents | web lanes | sources | rewrite | extras |
|---|---|---|---|---|---|
| lite | 1 | ollama | 3 | off | — |
| pro | 3 | ollama + tavily | 6 | 1 pass | full repair loop, incl. the lead |
| deep | 4 | + openalex | 10 | 2 passes | red-team agent, 3D provenance graph, flowchart, reporter agent → HTML audit report |
| **auto** | — | — | — | — | the router picks lite/pro/deep from the question |

(Corpus runs use the same depth presets; the "lanes" become the dense + keyword retrievers.)

---

## The cache is the demo

`RESEARCH_MODE=live|auto|replay`. Every outbound LLM / search / **embedding** call is
content-addressed and recorded in a committed SQLite DB.

- `auto` — read-through, records on miss. **dev default**
- `replay` — cache only, hard error on miss. **demo default**

A deep run costs ~100 external calls against a free tier whose limits are unpublished. Warm it,
commit the cache, and rehearse **with the wifi physically off**. Secrets are redacted **before
hashing and before storing** — so the cache can be committed *and* rotating a key doesn't bust it.

**DB round-trips never go through this cache** (they are stateful, not idempotent egress), so
corpus features are live-only; the web demo still replays offline.

---

## Persistence & the feature flag

- **Web research** is stateless: a run lives in an in-memory session (30-min TTL) and streams over
  resumable SSE. Reloading the page reattaches and replays the buffer instead of restarting.
- **Workspaces** are durable in Postgres.
- The entire workspace feature is **gated on `SUPABASE_DB_URL`**: unset → store disabled → the app
  boots and behaves exactly as the web-only version, and the DB drivers are never even imported.
  Set → the schema is migrated on startup and the corpus lane lights up.

---

## Configuration

All via `.env` (git-ignored). **No secrets in this file — placeholders only.**

```bash
# --- research providers ---
OLLAMA_API_KEY=            # required: chat models (kimi/minimax/qwen) on Ollama Cloud
TAVILY_API_KEY=            # optional: adds the Tavily search lane

# --- cache behaviour ---
RESEARCH_MODE=auto         # live | auto | replay   (auto = read-through, records on miss)

# --- workspaces / Graph-RAG (optional; absent => feature disabled) ---
# SUPABASE_DB_URL=postgresql://user:pass@host:5432/postgres          # runtime (pooler ok)
# SUPABASE_DB_DIRECT_URL=postgresql://user:pass@host:5432/postgres   # optional: direct, for migrations
# EMBED_MODEL=embeddinggemma        # bare name -> local ollama daemon
# EMBED_DIM=768                     # must match the model; baked into the vector column

# --- BYOK (optional per-stage overrides) ---
# GROQ_API_KEY= / OPENROUTER_API_KEY= / GEMINI_API_KEY=
```

Per-stage models are overridable via `PLANNER_MODEL`, `VERIFIER_MODEL`, `REWRITER_MODEL`, etc., and
per-run via `POST /api/research {models: {...}, keys: {...}}`.

**HTTP surface**

| route | does |
|---|---|
| `POST /api/research` | start a run `{question, mode, workspace?, keys?, models?, history?}` → `query_id` |
| `GET /api/research/stream?query_id=` | the SSE event stream (resumable via `Last-Event-ID`) |
| `POST /api/research/{query_id}/stop` | cancel a run |
| `GET /api/source/{id}?query_id=` | a cited source's full body (drawer highlights the quote) |
| `GET /api/artifact/{id}?query_id=` | a generated HTML artifact (audit report / task output) |
| `GET/POST/DELETE /api/workspaces[/{slug}]` | list / create / delete a workspace |
| `POST /api/workspaces/{slug}/ingest` | multipart file upload → ingestion |
| `GET /api/health` | mode, models, cache stats, store status, lane availability |

---

## Architecture map

```
backend/
  config.py            models per stage, mode presets, semaphores, EMBED_DIM, SUPABASE_DB_URL flag
  sessions.py          query_id -> question/mode/keys/models/workspace/sources/registry (30-min TTL)
  main.py              app wiring; migrates the store on startup iff enabled
  routers/
    research.py        POST /api/research; GET /stream (SSE); /source/{id}; /artifact/{id}
    workspace.py       workspace CRUD + multipart ingest
  providers/
    llm.py             façade: chat / complete / complete_json / EMBEDDINGS; routes on model-id prefix
    ollama.py          native /api/chat + /api/embed (local or cloud)
    openai_compat.py   Groq / OpenRouter / Google — BYOK chat + embeddings
    cache.py           content-addressed record/replay; REDACTS SECRETS before hashing + storing
    runcfg.py          per-run models + keys (ContextVars)
    lanes.py / rrf.py  web search lanes + Reciprocal Rank Fusion (lane-agnostic — reused for corpus)
  runtime/
    loop.py            agent tool loop: forced-verdict finalization, 80% nudge, retry, cancel
    tools.py           registry + dispatch + Ctx (carries the corpus binding)
    research_tools.py  web_search, read_page
    corpus_tools.py    corpus_search, corpus_read  (mirror research_tools; intern into SourceRegistry)
    report_tools.py    run_shell / run_python / write_file / make_document (sandboxed, cross-platform)
  pipeline/
    orchestrator.py    the run; async generator of SSE events; resolves router lane + auto depth
    router.py          intent (research|task) + auto depth (lite|pro|deep)
    planner, subagent, lead, claims, verify, rewrite, renumber, segment, sources, heatmap, report, doer, concept
  store/               (workspaces feature)
    db.py              asyncpg pool (ssl, statement_cache_size=0), register_vector, migrate
    migrations/0001_init.sql
    workspaces.py / documents.py / chunks.py    CRUD + the dense/keyword retriever SQL
  ingest/
    loaders.py         text/code/pdf -> Doc
    chunk.py           Doc -> chunks with offsets + locators
    embed.py           batched llm.embeddings
    pipeline.py        ingest_items(): the ingestion run
  retrieval/
    pipeline.py        retrieve(): embed query -> dense + keyword -> rrf.fuse
web/src/
  state/chat.ts        multi-turn store; workspaces slice; consumes the SSE stream
  lib/prose.tsx        renders the answer from authoritative text + offsets; marks per sentence
  components/
    Composer.tsx       question input + mode buttons (incl. auto)
    Workspaces.tsx     the corpus control: pill selector + drag-drop ingest + create/delete
    ExchangeView, Grid, SourceDrawer, Activity, Progress, Graph3D, Flowchart, Summary, Threads
```

---

## Tests

```bash
.venv/bin/python -m pytest tests/ -q       # 80 tests
```

- `test_renumber` — shared URLs collapse to one id; invented markers dropped, not guessed; offsets round-trip.
- `test_segment` / `test_respan` — `txt[s.start:s.end] == s.text` always; sentence ids survive retraction.
- `test_rewrite_cap` — a model that never produces a supported sentence burns exactly the cap, then retracts.
- `test_trust` — a retracted sentence can never raise the score.
- `test_runcfg` — BYOK overrides resolve per-run and never cross between concurrent runs.
- `test_report_tools` — the sandbox: writes stay inside the workspace; timeouts reap the process group; `run_shell` does real filesystem work.
- `test_router` — research vs task classification (incl. the polite-request cases) + auto-depth.
- `test_embeddings` — the facade routes by model id and caches like chat (replay-safe).
- `test_store` — the feature flag; DSN scrubbing; slug hygiene.
- `test_chunk` — chunk offsets round-trip; PDF/code locators are correct.

---

## Security

- `data/cache.sqlite` is committed on purpose (it's the demo), so `cache.py` redacts secrets
  recursively **before hashing and before storing**.
- API keys and the DB URL live only in `.env` (git-ignored) and in per-run memory (ContextVars,
  30-min TTL) — never logged, never cached, never echoed in events. DB connection errors are
  scrubbed of the DSN before they can reach a log or an SSE event.
- **Rotate any credential that was ever pasted in plaintext** (e.g. the Supabase password, the
  Tavily key) after setup.

---

## Roadmap

The workspaces feature ships as a **Foundation MVP** (persistence + text/code/PDF ingestion +
hybrid dense+keyword retrieval + corpus-grounded verified answers + auto routing). Deferred, all
purely additive:

- **M4 — graph lane**: entity/relation extraction (adapts `concept.extract`) + recursive-CTE graph traversal as a third fused retriever.
- **M5 — non-naive polish**: query preprocessing (rewrite / expand / decompose / HyDE) + reranking, gated by depth.
- **M6 — more modalities**: images (vision caption/OCR → text chunks), then audio (ASR).
- **M7 — output generation**: **3D mesh CAD is built** (trimesh → GLB/STL + in-app viewer). Still
  pending: LaTeX → PDF, chart/graph exports, and true parametric B-rep CAD (STEP/fillets).
