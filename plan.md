# receipts — plan

*Updated 2026-07-16. The living plan. The old deep-dive lives at `~/.claude/plans/virtual-sprouting-sundae.md`.*

---

## 1. The pitch

**Everyone else cites. This verifies.**

Perplexity-style research chat is the most common hackathon project — judges have seen dozens, and
a clone reads as an API wrapper. But the category has a real, documented failure: **citation
infidelity**, confidently citing a source that doesn't support the claim. The Tow Center studied
eight AI search engines; all of them do it.

So: **receipts** decomposes your question, researches the parts in parallel, then checks every
claim it wrote against the actual text of the source it cited — using a different model that never
sees the question or the answer. What fails gets rewritten against the real evidence or honestly
withdrawn. Then it shows you the work.

**The line for judges:** "This is the only research app that will tell you which of its own
sentences didn't survive fact-checking."

**The proof it's real:** on the very first run, a sub-agent that had read exactly two pages cited
`[3]`. The code caught it and said so. We didn't stage that — it's the failure the design exists
to catch, caught within minutes of first contact.

---

## 2. How a question flows

```
question
  ├─ planner            → N subqueries, each tagged with a search lane
  │                       (deep adds a RED TEAM agent hunting disconfirming evidence)
  ├─ N researchers in parallel, each with its own tool loop:
  │     web_search  → Ollama + Tavily + OpenAlex fired together, fused with RRF
  │     read_page   → Ollama fetch → Jina Reader fallback → drop
  │     every page read is interned into the SourceRegistry
  │  → draft with LOCAL [1..n] citations
  ├─ renumber   local → global, IN CODE. invented markers dropped, never guessed
  ├─ segment    exact char offsets. no model.
  ├─ claims     atomic claims from CITED sentences only
  ├─ verify     verify_pair(claim, source_text) per (claim, cited source)
  ├─ rewrite    failing sentences repaired against real evidence, or RETRACTed. cap in code.
  ├─ lead       merges the sub-answers — no search tools, never sees a source body
  ├─ verify     THE LEAD TOO, against text it never saw → then the SAME repair pipeline
  └─ deep only  provenance graph (pure code) + reporter agent → HTML audit report
```

### The five things that make it real

**1. The verifier cannot grade its own homework.**
`verify_pair(claim_text: str, source_text: str) -> Verdict` takes exactly two strings. There is no
parameter for the question, the answer, sibling claims, or other sources. Context leakage is
structurally impossible without changing the signature — not a prompt discipline someone has to
remember.

**2. The verifier cannot fake support.**
It must return a quote it claims is in the source. The server then looks for that quote with
`str.find()`. Not there + verdict was `supported` → **downgraded to `weak`**. Support is checked by
string search, not by a model's say-so.

**3. Citation numbers never touch a model.**
Researchers cite small local numbers (`[1]`, `[2]`) — the regime models are reliable in. A
`SourceRegistry` allocates global ids at retrieval time and pure, unit-tested code remaps them.
Asking a model to renumber across N documents fails *silently* on exactly the thing being judged.

**4. RETRACT is the mechanism, not the fallback.**
A model with no legal way to say "I can't support this" will invent something. Making retraction a
first-class, explicitly-praised output is what converts a hallucination generator into an honest
one. Failed claims surface in **"What we could not establish"** — a section derived from real
verification failures, not a model's hedging instinct.

**5. Row identity is permanent.**
Sentence ids are assigned once and only carried forward (`segment.respan`). Re-segmenting after a
repair silently renumbers every later sentence — iteration-1 verdicts land on the wrong rows and
the first-draft toggle diffs unrelated text. A withdrawn sentence keeps its row as a zero-width
span: struck through, never deleted. *A grid that resolves clean by deleting its own failures is a
lie.*

---

## 3. Feature status

### Done, and validated on real questions
| Feature | Notes |
|---|---|
| Question split + parallel researchers | `asyncio.gather`, live wire feed |
| 3 search modes | lite (1 agent) / pro (3 + repair) / deep (4 + red team + everything) |
| Multi-lane search + RRF fusion | cross-lane agreement = corroboration |
| Deep read | a snippet is a lead, never a source — verifying against a snippet would violate our own doctrine |
| Citation registry + orphan catch | invented markers dropped and surfaced |
| Independent fact-check | blind signature; kimi verifies what minimax wrote |
| Quote enforcement | `str.find` + unicode folding, else downgrade |
| Rewrite loop + RETRACT | cap is a `range()`, not a prompt request |
| Lead verified **and repaired** | the merge is a second hallucination surface |
| "What we could not establish" + contradictions | derived from the verdict matrix, zero extra cost |
| Trust tally, ledger, SHOW FIRST DRAFT | iteration-0 frozen per cell |
| BYOK | per-stage models + keys, per-run via ContextVars, never cached/logged |
| Computer use = reporter agent | `run_python` / `write_file` / `make_document` → HTML report |
| Record/replay cache | committed; the demo runs from it |
| 45 unit tests | renumber, segment, respan, rewrite cap, runcfg, report tools, session id |

### Validating right now
- [ ] **Deep mode E2E** — red team + 3D graph + flowchart + audit report in one run *(deep3 in flight)*

### Left to do
- [ ] **Design pass** — user reviews "Paper Trail" mockup (scratchpad) or picks another direction.
      Current UI is a working light chat app; verdicts render as proofreader's marks in the prose.
- [ ] Warm all 3 demo questions **in their demo modes**, then `warm.py --check` replay rehearsal
- [ ] **First git commit** — the repo has ZERO commits right now
- [ ] Rehearse the 3-minute script end to end

---

## 4. The demo (3 min, replayed from cache)

Live is not an option: every Ollama Cloud call is 8–30s, a pro run is ~4 min and a deep run ~10+.
The cache isn't an optimization, it's the demo. `RESEARCH_MODE=replay` + a committed
`data/cache.sqlite`.

| # | Mode | Question | What it shows |
|---|---|---|---|
| 1 | lite | *What are the rate limits of Ollama's web search API?* | the basics, fast, mostly green |
| 2 | **pro** | *How much does Tavily's search API cost and what does the free tier include?* | **the money shot** |
| 3 | deep | *Do AI search engines cite sources accurately?* | red team, conflicts, 3D graph, audit report |

**Why Q2 is the pitch:** pricing is widely misreported by blogspam, so researchers write things
their sources don't support — and they did. Real, reproducible catches from the pro4 run:

- *"…billed per seat"* → source describes credit-based pricing, never per-seat → **rewritten**
- *"no credit card required"* → source never says it → **rewritten to what the page actually says**
- 7 sentences with no honest version available → **withdrawn, shown struck through with reasons**
- Final: **22/38 claims held up (0.697)** — and the answer leads with a healed sentence

Then flip **SHOW FIRST DRAFT**: every mark snaps back to the confident, wrong original. That single
gesture is the entire thesis.

**An all-green board proves nothing** — it's indistinguishable from one that isn't wired up. The
red mark IS the product.

---

## 5. Architecture map

```
backend/
  config.py            models per stage, mode presets, semaphores
  sessions.py          query_id → question/mode/keys/models/sources/artifacts (30-min TTL)
  routers/research.py  POST /api/research → query_id; GET /stream (SSE); /source/{id}; /artifact/{id}
  providers/
    cache.py           content-addressed record/replay. REDACTS SECRETS before hashing + storing
    ollama.py          native /api/chat — the verified path
    openai_compat.py   Groq / OpenRouter / Google — BYOK
    runcfg.py          per-run models + keys (ContextVars — concurrent runs can't cross)
    llm.py             façade; routes on model id prefix
    websearch.py       lanes + RRF fusion
  runtime/
    loop.py            agent tool loop: forced-verdict finalization, 80% nudge, retry, cancel
    tools.py           registry + dispatch + Ctx
    research_tools.py  web_search, read_page
    report_tools.py    run_python, write_file, make_document (sandboxed per run)
  pipeline/
    orchestrator.py    the run; async generator of SSE events
    planner, subagent, lead, claims, verify, rewrite, renumber, segment, sources, heatmap, report
web/src/
  state/chat.ts        multi-turn chat store; one Exchange per question
  lib/prose.tsx        renders answer from authoritative text + offsets; marks per sentence
  components/          Wire, Ledger, ExchangeView, SourceDrawer, Composer, Graph3D, Flowchart
```

---

## 6. Hard-won facts — do not relearn these

**Latency & concurrency**
- Every Ollama Cloud call is 8–30s. Lite ≈ 4 min live, deep ≈ 10+.
- Ollama **serializes** `qwen3.5:397b` server-side: sem=12 measured *slower* than sem=6.
- **Bound every fan-out globally, not per-call.** Verify sem=6, rewrite sem=3. A per-call
  semaphore multiplies by the number of agents: deep fired 29 concurrent rewrites at a serialized
  model and wedged 14 of them.
- httpx timeout is a **per-read stall budget** (120s), not a total cap — a healthy stream resets it
  every chunk. The old 600s "total" turned one stall into a 10-minute black hole.
- Stalls and drops arrive as **httpx exceptions, not LLMError** — the retry ladder must catch both,
  or the flakiest failures are the only ones never retried.

**Models (measured, not guessed — 6k-char source, sem=6, uncached)**
| model | accuracy | speed | verdict |
|---|---|---|---|
| `kimi-k2.6` | 7/7 | 1.47s | **the verifier** |
| `qwen3.5:397b` | 7/7 | 6.6s | the rewriter (third family, few calls) |
| `groq/gpt-oss-120b` | 7/7 | 3.52s | accurate, but see the token cap below |
| `groq/llama-3.3-70b` | **5/7 — misses contradictions** | 2.47s | never |

Three families on purpose: **minimax writes → kimi verifies → qwen repairs.** Never let the
rewriter share a family with the verifier, or the fix gets graded by its own author.

**⚠️ Groq cannot be the verifier on a free tier — and I got this wrong TWICE.**
- Attempt 1: benchmarked `stream=False` + one reused client → "10× faster". Through the real
  streaming path it was *slower*. Retracted.
- Attempt 2: Ollama degraded ~20× (transient, ~15 min), so I tested Groq on a **200-char** source
  → "5/5 at 0.34s, 90× faster" → shipped it. The real path sends a **6,000-char** source per call
  and Groq's free tier caps ~**8k tokens/minute** — not requests. Headers told the truth:
  `x-ratelimit-remaining-requests: 915` while `remaining-tokens: 7300`. That allows ~4 verifies a
  minute. Two agents got through, the third silently fell back to the slow model. Reverted.

**The lesson, stated plainly:** an isolated benchmark controls away the variable that decides the
outcome. Re-measure through the real path, at the real payload size, at the real volume — and
check *which* rate-limit dimension binds. Provider latency also swings hour to hour: Ollama went
1.47s → 30s → 2.4s inside one afternoon. Any single measurement is a snapshot, not a constant.
**None of this touches the demo, which replays from cache and calls nobody.**

**Traps**
- Unicode quotes: pages use `’`, models retype `'` → `str.find` misses → every true claim
  downgrades. `_UNI` fold table in verify.py is load-bearing.
- `pgrep -f "backend.pipeline.orchestrator"` **matches its own shell** and kills the session. Kill
  by explicit PID. (Done this twice.)
- The CLI truncates events to 220 chars for readability → unparseable JSON. Use `--jsonl`.
- Ollama's `content` field is a **snippet** — never use it as a source body. Tavily `raw_content`
  and OpenAlex abstracts are legitimate bodies.
- Session id: `meta.query_id` must be the id the session is keyed by, or citation clicks 404.

**Security**
- `data/cache.sqlite` is **committed on purpose** — it's the demo. So `cache.py` redacts secrets
  recursively *before hashing and before storing*. Redacting before hashing also means rotating a
  key doesn't bust the cache.
- The Tavily key was pasted in plaintext in chat → **rotate it after the hackathon**. It lives only
  in `.env` (chmod 600, gitignored).
- `OLLAMA_API_KEY` comes from `~/jarvis-data/secrets.env`. Never printed.
- BYOK keys: memory only, 30-min TTL, never logged, never cached, never echoed in events.

---

## 7. Risks now

1. **Design is unresolved** and the user has rejected one direction already. The functionality is
   done; the skin is the open question. Mitigation: mockup exists, backend is skin-agnostic — the
   SSE contract doesn't change.
2. **Deep mode is slow even when healthy** (~10 min). Mitigation: the demo replays from cache;
   deep3 is measuring the real number post-fix.
3. **Zero git commits.** Everything is one `rm` from gone. Fix this next.
4. **Cache must cover all 3 questions in their demo modes.** A replay miss on stage = a hang.
   `warm.py --check` is the gate.
