# receipts

**Everyone else cites. This verifies.**

A research chat that decomposes your question, researches the parts in parallel, and then checks
every claim it wrote against the actual text of the source it cited — using a different model that
never sees the question or the answer. Claims that fail get rewritten against the real evidence, or
honestly retracted.

The documented failure of AI search is *citation infidelity*: confidently citing a source that
doesn't support the claim. Perplexity does it. This catches it, repairs it, and shows you the work.

---

## Run it

```bash
cp .env.example .env          # add OLLAMA_API_KEY, TAVILY_API_KEY (optional)
python -m venv .venv && .venv/bin/pip install httpx fastapi uvicorn pytest
.venv/bin/uvicorn backend.main:app --port 8000    # terminal 1
cd web && npm install && npm run dev              # terminal 2 -> localhost:5173
```

No browser needed to debug — every stage streams as JSON from the CLI:

```bash
.venv/bin/python -m backend.pipeline.orchestrator "your question" --mode pro --quiet
```

## The pipeline

```
question
  ├─ planner            -> N independent subqueries, each tagged with a search lane
  │                        (deep mode adds a RED TEAM agent hunting disconfirming evidence)
  ├─ N sub-agents in parallel (asyncio.gather), each with its own tool loop:
  │     web_search  -> Ollama + Tavily + OpenAlex fired together, fused with RRF
  │     read_page   -> Ollama fetch -> Jina Reader fallback -> drop
  │     every page read is interned into the SourceRegistry
  │  -> draft with LOCAL [1..n] citations
  ├─ renumber   local -> global, IN CODE. invented markers dropped, never guessed
  ├─ segment    exact char offsets. no model.
  ├─ claims     atomic claims from CITED sentences only
  ├─ verify     verify_pair(claim, source_text) per (claim, cited source)
  ├─ rewrite    failing sentences repaired against real evidence, or RETRACTed. cap in code.
  ├─ lead       merges the sub-answers — with no search tools and no source bodies
  ├─ verify     THE LEAD TOO, against text it never saw — then the SAME repair pipeline
  └─ deep mode  provenance graph (pure code) + reporter agent
                (run_python / write_file / make_document -> HTML artifact)
```

**Row identity is permanent.** Sentence ids are assigned once, at first segmentation, and only
ever carried forward (`segment.respan`). Re-segmenting after a repair silently renumbers every
later sentence — iteration-1 verdicts land on the wrong rows and the first-draft toggle diffs
unrelated text. A retracted sentence keeps its row as a zero-width span: the board strikes it
through instead of letting the grid resolve clean by deleting its own failures.

## The four things that make it real

**1. The verifier cannot grade its own homework.**
`verify_pair(claim_text: str, source_text: str) -> Verdict` takes exactly two strings. There is no
parameter for the question, the answer, sibling claims, or other sources. Context leakage is
structurally impossible without changing the signature — not a prompt discipline someone has to
remember.

**2. The verifier cannot fake support.**
It must return a quote it claims is in the source. The server then looks for that quote with
`str.find()`. If it isn't literally there and the verdict was `supported`, the server **downgrades
it to `weak`**. Support is checked by string search, not by a model's say-so.

**3. Citation numbers never touch a model.**
Each sub-agent cites small local numbers (`[1]`, `[2]`) — the regime models are reliable in. A
`SourceRegistry` allocates global ids at retrieval time and pure, unit-tested code remaps them.
Asking a model to renumber across N documents fails *silently* on exactly the thing being judged.

> This is not theoretical. On the first real run, a sub-agent that had read two pages confidently
> cited `[3]` — a source it never opened. The code dropped it and the UI said so.

**4. `RETRACT` is the mechanism, not the fallback.**
A model with no legal way to say "I can't support this" will invent something. Making retraction a
first-class, explicitly-praised output is what converts a hallucination generator into an honest
one. Failed claims surface in **"What we could not establish"** — a section derived from real
verification failures, not a model's hedging instinct.

## Models — three families, and that's the point

| stage | model | why |
|---|---|---|
| planner | `kimi-k2.6:cloud` | 1 call, pure JSON, blocks everything -> optimise latency |
| **sub-agent** | `minimax-m3:cloud` | the writer |
| claims | `kimi-k2.6:cloud` | JSON reliability, not depth |
| **verifier** | `kimi-k2.6:cloud` | **different family from the writer**, 7/7 on the battery |
| **rewriter** | `qwen3.5:397b:cloud` | **third family** — the repair is judged by neither writer nor verifier |
| lead | `minimax-m3:cloud` | the visible centrepiece |

Measured, not guessed (6k-char source, sem=6, uncached):

| model | verify accuracy | throughput | 45 verdicts |
|---|---|---|---|
| `kimi-k2.6` | **7/7** | 1.47s ea | **~66s** |
| `qwen3.5:397b` | 7/7 | 6.6s ea | ~300s |
| `groq/openai/gpt-oss-120b` | 7/7 | 3.52s ea | ~158s |
| `groq/llama-3.3-70b` | 5/7 — misses contradictions | 2.47s ea | — |

Ollama Cloud **serialises** `qwen3.5:397b` server-side: `sem=12` measured *slower* than `sem=6`
(151s vs 79s for 12 calls). Raising concurrency does not help it.

BYOK is wired end-to-end, per run: `POST /api/research {models: {stage: id}, keys: {provider: key}}`
routes any stage to a namespaced id (`groq/…`, `openrouter/…`, `google/…`) via
`providers/openai_compat.py`. Overrides live in ContextVars (`providers/runcfg.py`) so two
concurrent runs can never see each other's models — or keys. Keys are never logged, never cached,
never echoed back. Defaults stay on the measured Ollama path.

**Transport doctrine:** the httpx timeout is a *per-read stall budget* (120s), not a total cap — a
healthy stream resets it on every chunk. And stalls/mid-stream drops arrive as `httpx` exceptions,
not polite server errors, so the retry ladder catches those too. The 600s "total" timeout it
replaced turned one server-side stall into a 10-minute black hole; two runs "hung" at lead-verify
paying exactly that.

## Search modes

| mode | agents | lanes | sources | rewrite | extras |
|---|---|---|---|---|---|
| lite | 1 | ollama | 3 | off | — |
| pro | 3 | ollama + tavily | 6 | 1 pass | full repair loop, incl. the lead |
| deep | 4 | + openalex | 10 | 2 passes | red-team agent, 3D provenance graph, flowchart, reporter agent -> HTML audit report |

## The cache is the demo

`RESEARCH_MODE=live|auto|replay`. Every outbound call is content-addressed and recorded.

- `auto` — read-through, records on miss. **dev default**
- `replay` — cache only, hard error on miss. **demo default**

A deep run costs ~100 external calls against a free tier whose limits are unpublished. Warm it,
commit `data/cache.sqlite`, and rehearse **with the wifi physically off**:

```bash
.venv/bin/python scripts/warm.py            # record the demo questions
.venv/bin/python scripts/warm.py --check    # replay-only; must pass offline
```

Secrets are redacted **before hashing and before storing** — `cache.sqlite` is committed, and the
request payload carries API keys. Redacting before hashing also means rotating a key doesn't bust
the cache.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q       # 45 tests
```

- `test_renumber.py` — shared URLs collapse to one id, disjoint agents remap independently,
  invented markers are dropped not guessed, offsets round-trip after renumbering.
- `test_segment.py` — `txt[s.start:s.end] == s.text` always; no splitting on decimals,
  abbreviations, or inside code fences.
- `test_rewrite_cap.py` — a model that *never* produces a supported sentence burns exactly
  `MAX_REWRITE_ITERS` attempts and then retracts. The cap is a `range()`, not a request.
- `test_respan.py` — sentence ids survive retraction (the row that was s3 must never become s2);
  retracted rows still reach the board carrying their reason; markdown structure survives repair.
- `test_runcfg.py` — BYOK overrides resolve per-run and never cross between concurrent runs.
- `test_report_tools.py` — the reporter's sandbox: writes stay inside the workspace, timeouts
  kill, tracebacks are model-actionable output.
- `test_session_id.py` — the id in `meta` is the id the session is keyed by (source lookups 404'd
  when the orchestrator minted its own).

The CLI streams every event as pretty-printed JSON; add `--jsonl` for full untruncated
machine-readable output you can pipe into anything.
