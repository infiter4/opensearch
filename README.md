# opensearch

**Everyone else cites. This verifies.**

opensearch is a research chat that splits your question into parts and researches them in
parallel. Then it checks **every claim it wrote against the actual text of the source it cited**.
The checker is a *different model that never sees the question or the answer*. Claims that fail
get rewritten against the real evidence, or retracted. Then it shows you the work.

The known failure of AI search is **citation infidelity**: citing a source that doesn't support
the claim. opensearch catches it, repairs it, and shows you what didn't survive.

> **Status: user testing.** Expect rough edges. See [Giving feedback](#giving-feedback) and
> [Known limitations](#known-limitations).

---

## Contents

1. [Quick start](#quick-start)
2. [Setting up your API keys](#setting-up-your-api-keys)
3. [What's new](#whats-new)
4. [Using it](#using-it)
5. [What to try (testing guide)](#what-to-try-testing-guide)
6. [How it works](#how-it-works)
7. [Workspaces: research your own documents](#workspaces-research-your-own-documents)
8. [Models](#models)
9. [Configuration reference](#configuration-reference)
10. [HTTP API](#http-api)
11. [Architecture map](#architecture-map)
12. [Tests](#tests)
13. [Security](#security)
14. [Known limitations](#known-limitations)
15. [Roadmap](#roadmap)

---

## Quick start

**You need:** Python 3.11+, Node 20+, and an **Ollama Cloud API key**
([details below](#setting-up-your-api-keys)).

```bash
git clone https://github.com/infiter4/opensearch.git
cd opensearch
cp .env.example .env            # then open .env and paste your keys
```

**Backend** (terminal 1):

```bash
# macOS / Linux
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn backend.main:app --port 8000
```

```powershell
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\uvicorn backend.main:app --port 8000
```

**Frontend** (terminal 2):

```bash
cd web
npm install
npm run dev
```

Open **http://localhost:5173**.

**Check it's wired up:** open http://localhost:8000/api/health. Under `lanes`, `"ollama": true`
means your key was picked up, and `"tavily": true` means the Tavily key was too.

---

## Setting up your API keys

All keys go in `.env` in the project root. That file is **git-ignored**, so never commit it, and
never paste keys into issues or screenshots.

| Key | Needed? | What it does | Where to get it |
|---|---|---|---|
| `OLLAMA_API_KEY` | **Required** | Runs every chat model and the main web-search lane | [ollama.com/settings/keys](https://ollama.com/settings/keys) (sign in → *Add API key*) |
| `TAVILY_API_KEY` | Recommended | Adds a second web-search lane in **pro** and **deep** modes | [app.tavily.com](https://app.tavily.com) (free tier available) |
| `GROQ_API_KEY` | Optional | Lets you run any stage on Groq (`groq/<model>`) | [console.groq.com/keys](https://console.groq.com/keys) |
| `OPENROUTER_API_KEY` | Optional | Lets you run any stage on OpenRouter (`openrouter/<model>`) | [openrouter.ai/keys](https://openrouter.ai/keys) |
| `GEMINI_API_KEY` | Optional | Lets you run any stage on Gemini (`google/<model>`) | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |

OpenAlex (academic search, used in deep mode) and Jina Reader (page-fetch fallback) need no key.

A minimal `.env`:

```bash
OLLAMA_API_KEY=your-ollama-key
TAVILY_API_KEY=your-tavily-key
RESEARCH_MODE=live
```

**Rules for the file:**

- Write `KEY=value` with no spaces around `=`. Quotes are optional.
- A `#` only starts a comment when there's a space before it, so a `#` inside a password is safe.
- Real environment variables override `.env`.
- Restart the backend after editing `.env`.

**Using a different provider for one stage.** Add that provider's key, then point the stage at
it with a prefixed model id:

```bash
GROQ_API_KEY=your-groq-key
VERIFIER_MODEL=groq/llama-3.3-70b-versatile
```

Keep the writer, verifier and rewriter on **different model families**. See [Models](#models)
for why.

**Per-request keys.** API clients can also pass keys and models per run, in the body of
`POST /api/research`: `{"keys": {...}, "models": {...}}`. These are held in memory for that run
only (30-minute TTL). They are never logged, cached or written to disk.

---

## What's new

Since the last release:

- **Renamed** from *receipts* to **opensearch**.
- **Redesigned UI.** A new layout and a light/dark theme (remembered per browser).
- **Conversation threads.** Past conversations are kept in the sidebar and can be deleted.
  Follow-up questions carry the conversation's history.
- **Resumable runs.** Reloading the page mid-run reattaches to the live stream instead of
  restarting it. A **Stop** button cancels a run.
- **Auto mode.** The router picks the depth (`lite` / `pro` / `deep`) from your question.
- **Task lane (computer use).** Ask it to *do* something ("turn this into a PDF", "design an
  L-bracket and export an STL"). A sandboxed agent does it and returns a downloadable file. 3D
  models open in an in-app viewer.
- **Workspaces (optional).** Upload text, code or PDFs and research *your own documents*, with
  the same claim-by-claim verification. Requires Postgres + pgvector.
- **Provenance graph and flowchart** (deep mode). They show how the answer's claims connect to
  their sources.
- **Reliability.** Over 30 pipeline and infrastructure bugs fixed. Each fix has a regression
  test covering stuck runs, lost deletes, duplicate stream events, citation placement, the sandbox
  and secret scrubbing.
- **Removed** the demo-only replay cache, demo scripts and hard-coded demo questions. Every run
  now calls the live providers by default (`RESEARCH_MODE=live`).

---

## Using it

Type a question and pick a depth:

| depth | agents | web search | sources | repair passes | extras | typical time |
|---|---|---|---|---|---|---|
| **lite** | 1 | Ollama | 3 | 0 | — | fastest |
| **pro** | 3 | Ollama + Tavily | 6 | 1 | full repair loop, including the merged answer | a few minutes |
| **deep** | 4 | + OpenAlex | 10 | 2 | red-team agent, provenance graph, flowchart, HTML audit report | ~10 min |
| **auto** | — | — | — | — | picks one of the above from your question | — |

**Reading the answer:**

- Each sentence is marked by how well its citation held up. Click a citation to open the source
  drawer, which highlights the exact supporting quote.
- **Retracted** sentences stay visible, struck through, instead of silently disappearing.
- **"What we could not establish"** lists claims that failed verification and couldn't be
  repaired.
- The activity panel shows each stage live: planning, searching, reading, verifying, rewriting.

**Asking it to do things.** Inputs like "make this a PDF" or "create a 3D model of a phone
stand" go to the task lane instead of research. You get a downloadable artifact.

---

## What to try (testing guide)

These are a good spread to start with:

1. **A simple fact** in `lite`: *"What are the rate limits of the Ollama web search API?"*
2. **A comparison** in `pro`: *"How do Tavily's and Exa's search API pricing compare?"*
3. **Something contested** in `deep`: *"Do AI search engines cite their sources accurately?"* Look
   for red/retracted claims and open the audit report.
4. **`auto` mode** with a mix of short and broad questions. Did it pick a sensible depth?
5. **A follow-up** in the same thread ("and what about the free tier?").
6. **Stop and reload.** Stop a run mid-way, and reload the page during another.
7. **A task:** *"Design a simple L-bracket and export it as an STL."*
8. **Workspaces** (if enabled): upload a PDF and ask about its contents.

What we most want to hear about:

- A citation that **doesn't actually support** its sentence and wasn't flagged.
- A claim that was **retracted or flagged but was actually correct**.
- Runs that hang, error or take far longer than the table above.
- Anything confusing in the UI.

### Giving feedback

Open an issue at https://github.com/infiter4/opensearch/issues and include:

- the question and the depth you used,
- what you expected and what happened,
- a screenshot if it's a UI problem (**check that no keys are visible**),
- any errors from the backend terminal or the browser console.

---

## How it works

Every message first hits an **intent router**:

```
input
 └─ router.classify()  ──────────────┬── kind = task ───────▶  TASK lane  (computer use)
     · research vs task              │                          run_shell / run_python /
     · auto depth: lite|pro|deep     │                          write_file / make_document / make_model
                                     │
                                     └── kind = research ───▶  RESEARCH pipeline
                                          │
                              workspace selected?  ─ no ─▶  WEB lane     (web_search / read_page)
                                          │
                                          └─ yes ────▶  CORPUS lane  (corpus_search / corpus_read)
```

The router is code-first. A keyword fast path settles most inputs with no model call. Only
ambiguous ones go to a small JSON model call, and any failure defaults to `research`.

### The research pipeline

```
question
  ├─ planner            -> N independent subqueries (deep adds a RED TEAM agent)
  ├─ N sub-agents in parallel, each with its own tool loop:
  │     web:     web_search -> Ollama + Tavily + OpenAlex together, fused with RRF
  │              read_page  -> Ollama fetch -> Jina Reader fallback
  │     corpus:  corpus_search -> dense (pgvector) + keyword (tsvector), fused with RRF
  │  -> draft with LOCAL [1..n] citations
  ├─ renumber   local -> global ids, in code; invented citations dropped, never guessed
  ├─ segment    exact character offsets, no model
  ├─ claims     atomic claims from cited sentences only
  ├─ verify     verify_pair(claim, source_text) for every (claim, cited source)
  ├─ rewrite    failing sentences repaired against real evidence, or RETRACTED
  ├─ lead       merges the sub-answers (no search tools, no source bodies)
  ├─ verify     the merged answer too, against text the lead never saw
  └─ deep       provenance graph + reporter agent -> HTML audit report
```

### Why you can trust the checks

1. **The verifier can't grade its own homework.** `verify_pair(claim_text, source_text)` takes
   exactly two strings: no question, no answer, no sibling claims. It runs on a different model
   family from the writer.
2. **The verifier can't fake support.** It must return a quote from the source. The server
   searches for that quote literally. If it isn't there, a `supported` verdict is downgraded to
   `weak`.
3. **Citation numbers never touch a model.** Agents cite small local numbers. Unit-tested code
   maps them to global ids and drops invented citations.
4. **Retraction is a first-class output.** The model always has an honest way out, so it doesn't
   invent support. The rewrite cap is a `range()`, not a request. Hitting it auto-retracts.
5. **The merge is verified too.** The lead's combined answer goes through the same
   verify → rewrite → retract pipeline.

---

## Workspaces: research your own documents

A **workspace** is a saved project holding uploaded documents. Select one, and research runs over
**your documents** instead of the web, with every sentence checked against your own text.

**Extra setup** (skip this to run web-only):

1. A Postgres database with the **pgvector** extension, for example a free Supabase project. Put
   its URL in `.env` as `SUPABASE_DB_URL`. Optionally, put a direct (non-pooler) URL in
   `SUPABASE_DB_DIRECT_URL` for migrations. The schema is created on startup.
2. A local **Ollama** install for embeddings: run `ollama serve`, then
   `ollama pull embeddinggemma`. Ollama Cloud gates embeddings on the free tier, so they run
   locally (and your documents embed offline).

Then use the workspace control in the UI to create a workspace and drag in files.

- **Supported files:** text/markdown, source code (cited by line range), PDF (cited by page).
- **Ingestion:** files are split into ~512-token chunks with exact offsets, embedded (768-dim),
  and stored with a full-text index. Duplicate files are skipped.
- **Retrieval:** dense vector search and keyword search run together and are fused with
  Reciprocal Rank Fusion, the same method the web lane uses.
- `/api/health` → `store.enabled` tells you whether workspaces are on.

---

## Models

| stage | default model | why |
|---|---|---|
| planner / claims / **verifier** / router | `kimi-k2.6:cloud` | reliable JSON; **different family from the writer** |
| **sub-agent / lead** (the writer) | `mistral-large-3:675b:cloud` | writes the answer |
| **rewriter** | `qwen3.5:397b:cloud` | **third family**: neither the writer nor the verifier judges the repair |
| reporter / doer | `kimi-k2.7-code:cloud` | strong tool use |
| embedder | `embeddinggemma` (local) | 768-dim, offline |

The rule: **one family writes, another verifies, a third repairs.** If you override models, keep
it that way, or the fix gets graded by its own author. If the verifier keeps hitting rate limits,
it falls back to `qwen3.5:397b:cloud`.

---

## Configuration reference

Everything is set in `.env`. See [`.env.example`](.env.example) for a commented template.

| variable | default | meaning |
|---|---|---|
| `OLLAMA_API_KEY` | — | **required** |
| `TAVILY_API_KEY` | — | enables the Tavily search lane |
| `GROQ_API_KEY` / `OPENROUTER_API_KEY` / `GEMINI_API_KEY` | — | enable `groq/…`, `openrouter/…`, `google/…` model ids |
| `RESEARCH_MODE` | `live` in `.env.example` (code fallback: `auto`) | `live` = always call providers; `auto` = reuse identical past calls from `data/cache.sqlite`; `replay` = cache only |
| `PLANNER_MODEL`, `SUBAGENT_MODEL`, `CLAIMS_MODEL`, `VERIFIER_MODEL`, `REWRITER_MODEL`, `LEAD_MODEL`, `REPORTER_MODEL`, `ROUTER_MODEL`, `DOER_MODEL` | see [Models](#models) | per-stage model override |
| `SUPABASE_DB_URL` | unset | Postgres URL; setting it enables workspaces |
| `SUPABASE_DB_DIRECT_URL` | unset | direct URL used for migrations |
| `EMBED_MODEL` / `EMBED_DIM` | `embeddinggemma` / `768` | embedding model; the dimension is fixed per workspace |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | local Ollama daemon (embeddings) |
| `OLLAMA_MAX_INFLIGHT` | `3` | max simultaneous Ollama requests; raise only on a paid tier |
| `SEM_VERIFY` | `4` | max parallel verifier calls |

---

## HTTP API

| route | does |
|---|---|
| `POST /api/research` | start a run `{question, mode, workspace?, keys?, models?, history?}` → `query_id` |
| `GET /api/research/stream?query_id=` | SSE event stream (resumable via `Last-Event-ID`) |
| `POST /api/research/{query_id}/stop` | cancel a run |
| `GET /api/source/{id}?query_id=` | a cited source's full text |
| `GET /api/artifact/{id}?query_id=` | a generated artifact (audit report / task output) |
| `GET/POST/DELETE /api/workspaces[/{slug}]` | list / create / delete a workspace |
| `POST /api/workspaces/{slug}/ingest` | multipart file upload → ingestion |
| `GET /api/health` | mode, models, store status, which search lanes have keys |

**Debug without a browser.** Every stage streams as JSON from the CLI:

```bash
.venv/bin/python -m backend.pipeline.orchestrator "your question" --mode pro --quiet
# add --jsonl for full, untruncated output
```

---

## Architecture map

```
backend/
  config.py            .env loading, per-stage models, depth presets, concurrency limits
  sessions.py          per-run state (30-min TTL)
  main.py              app wiring; migrates the store on startup if enabled
  routers/             research.py (runs, SSE, sources, artifacts) · workspace.py (CRUD + ingest)
  providers/
    llm.py             chat / complete / embeddings facade; routes on model-id prefix
    ollama.py          Ollama chat + embed (local or cloud)
    openai_compat.py   Groq / OpenRouter / Gemini (BYOK)
    cache.py           optional record/replay cache; redacts secrets before hashing + storing
    runcfg.py          per-run models + keys (ContextVars, isolated between concurrent runs)
    lanes.py / rrf.py  web search lanes + Reciprocal Rank Fusion
  runtime/             agent tool loop + tools (web, corpus, sandboxed shell/python/files)
  pipeline/            orchestrator, router, planner, subagent, lead, claims, verify, rewrite,
                       renumber, segment, sources, heatmap, report, doer, concept
  store/               Postgres + pgvector (workspaces, documents, chunks) + migrations
  ingest/              loaders (text/code/pdf) → chunk → embed → store
  retrieval/           dense + keyword retrieval fused with RRF
web/src/
  state/chat.ts        threads, workspaces, SSE consumer
  components/          Composer, ExchangeView, Grid, SourceDrawer, Activity, Progress,
                       Graph3D, Flowchart, ModelViewer, Summary, Threads, Workspaces
```

---

## Tests

```bash
.venv/bin/python -m pytest tests/ -q     # hermetic: no network, no live model calls
cd web && node e2e.mjs                   # drives the real UI in Chromium (needs vite :5173 + backend :8000)
```

On Windows, use `.venv\Scripts\python`. The `e2e.mjs` suites are `boot errors flow stop reload
task mobile deep`. `boot`, `errors` and `mobile` never start a paid run. The rest make real API
calls.

---

## Security

- API keys and the database URL live only in `.env` (git-ignored) and in per-run memory. They are
  never logged, cached or echoed in stream events. Database errors are scrubbed of the connection
  string.
- The optional cache (`auto`/`replay`) redacts secrets before hashing and storing. It's
  git-ignored and should never be committed.
- The task lane runs commands in a per-run sandbox directory, with timeouts and path-escape
  checks. It is **not** a security boundary against a hostile model, so run opensearch on a
  machine you're comfortable with.
- If a key was ever exposed (committed, pasted, screenshotted), **rotate it** at the provider.

---

## Known limitations

- **Task lane needs a POSIX shell.** Shell commands run under `/bin/sh`, so tasks work on macOS
  and Linux. On Windows, run the backend inside **WSL**. Research works natively on Windows.
- **Rate limits.** The free Ollama Cloud tier allows only about 3 concurrent requests. Deep runs
  make ~100 calls, so expect some slow stretches.
- **Deep mode is slow** (around 10 minutes).
- **Web research isn't saved on the server.** A run lives in memory for 30 minutes. Threads are
  stored in your browser only.
- **3D output is mesh-only** (GLB/STL). Parametric CAD (STEP, fillets) isn't supported yet.
- **Workspaces need extra setup** (Postgres + pgvector and a local Ollama daemon).

---

## Roadmap

- **Graph retrieval lane:** entity/relation extraction plus graph traversal as a third fused
  retriever.
- **Better retrieval:** query rewriting / expansion / HyDE and reranking, scaled by depth.
- **More file types:** images (captioning/OCR), then audio (speech-to-text).
- **More outputs:** LaTeX → PDF, chart exports, parametric CAD.
