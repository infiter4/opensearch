import { create } from "zustand";
import type {
  ClaimCheck, LedgerRow, LogEntry, LogKind, Researcher, Retraction, SentenceRef, SourceInfo,
  TrustTally, Verdict,
} from "../lib/protocol";

export type RunPhase =
  | "researching" | "checking" | "repairing" | "writing" | "done" | "error"
  // Cut off by a page reload. The server-side run cannot be re-attached to (the stream endpoint
  // starts a run, it does not resume one), so saying "interrupted" is the truthful state —
  // better than a spinner that will never move.
  | "interrupted";

export interface Exchange {
  key: string;               // client-side key, stable for React
  queryId: string | null;    // server session id, from the POST + meta
  question: string;
  mode: string;              // lite | pro | deep
  cacheMode: string;         // live | auto | replay
  kind?: "research" | "task";  // intent-router verdict: research question vs do-this task (CUA)
  routeTitle?: string;         // short label of what the router thought this was
  workspace?: string | null;   // corpus this run researched (slug), or null for the web
  resolvedMode?: string;       // the depth auto-mode actually picked (from meta.search_mode)
  phase: RunPhase;
  startedAt: number;
  elapsed: number;

  researchers: Record<string, Researcher>;
  order: string[];
  sources: Record<number, SourceInfo>;

  /** claim checks keyed `${sentence_id}:${source_id}` — the current state of every mark */
  checks: Record<string, ClaimCheck>;
  /** frozen iteration-0 copy of each check — powers the first-draft toggle */
  draft: Record<string, ClaimCheck>;
  repairing: Set<string>;
  healed: Set<string>;       // sentence_ids whose final mark improved on iteration 0

  /** the run log, in arrival order — every stage, with real elapsed times */
  log: LogEntry[];
  /** claims per agent, so the log can show what was actually extracted */
  claimsBy: Record<string, { id: string; sentence_id: string; text: string; source_ids: number[] }[]>;
  /** wall-clock of the last event. Silence is the normal shape of a provider backing off, and
   *  without this the UI cannot tell "working" from "wedged" — which is exactly what it looked
   *  like from outside. */
  lastAt: number;

  ledger: { rows: LedgerRow[]; cols: SourceInfo[] };
  answer: { text: string; sentences: SentenceRef[] };
  gaps: string[];
  conflicts: { sentence_id?: string; reason?: string }[];
  retracted: Retraction[];
  trust: TrustTally | null;
  notes: { scope: string; message: string }[];  // orphan catches, non-fatal errors — worth showing
  graph: { nodes: any[]; links: any[] } | null;  // deep mode: provenance graph
  artifacts: { id: string; name: string; url: string; kind: string }[];  // deep mode: reports
}

export interface Thread {
  id: string;
  title: string;      // the opening question, trimmed — what the sidebar shows
  created: number;
  updated: number;
  exchanges: Exchange[];
}

export interface WorkspaceInfo {
  slug: string; title: string;
  n_documents?: number; n_chunks?: number; embed_model?: string; embed_dim?: number;
}

interface ChatState {
  threads: Thread[];
  activeId: string;
  showDraft: Record<string, boolean>;   // per-exchange first-draft toggle
  openSource: { exKey: string; id: number; quote?: string | null } | null;
  focusSentence: string | null;

  // Corpus workspaces (backend feature-flagged on SUPABASE_DB_URL). activeWorkspace === null means
  // research the open web, exactly as before.
  workspaces: WorkspaceInfo[];
  activeWorkspace: string | null;
  storeEnabled: boolean;

  ask(question: string, mode: string): Promise<void>;
  listen(exKey: string, queryId: string): void;
  reattach(): void;
  stop(exKey: string): Promise<void>;
  retry(exKey: string): Promise<void>;
  apply(exKey: string, event: string, d: any): void;
  toggleDraft(exKey: string): void;
  viewSource(exKey: string, id: number, quote?: string | null): void;
  closeSource(): void;
  focus(sid: string | null): void;
  newThread(): void;
  openThread(id: string): void;
  deleteThread(id: string): void;

  loadWorkspaces(): Promise<void>;
  createWorkspace(title: string): Promise<string | null>;
  setActiveWorkspace(slug: string | null): void;
  deleteWorkspace(slug: string): Promise<void>;
  ingestFiles(files: File[]): Promise<{ documents: number; chunks: number; skipped: number } | null>;
}

/** The active thread's exchanges. Components read this instead of a flat list.
 *
 *  EMPTY is a module constant, not a fresh `[]`. As a zustand selector this runs on every store
 *  change and its result is compared by reference: a new array each call is never equal to the
 *  last, so React re-renders, which re-runs the selector — "Maximum update depth exceeded" and a
 *  blank page, with no component visibly at fault. */
const EMPTY: Exchange[] = [];
export const activeExchanges = (s: ChatState): Exchange[] =>
  s.threads.find((t) => t.id === s.activeId)?.exchanges ?? EMPTY;

const blankResearcher = (id: string, title = ""): Researcher => ({
  id, title, status: "spawned", text: "", sentences: [], orphans: [], iteration: 0, tools: [],
});

/* ——— persistence ————————————————————————————————————————————————
   Threads live in localStorage. Two things do not survive a plain JSON round-trip and both fail
   silently rather than loudly: Sets become `{}`, and the store is bigger than the ~5MB quota once
   a few deep runs pile up. So: encode Sets explicitly, cap the history, and prune-and-retry on
   QuotaExceeded rather than letting a save throw inside a state update. */

const LS_KEY = "receipts.threads.v1";
const MAX_THREADS = 8;
/** Refuse to even parse a store bigger than this. Measured: a deep thread is ~460KB. */
const MAX_STORE_BYTES = 3_500_000;

type StoredExchange = Omit<Exchange, "repairing" | "healed"> & {
  repairing: string[]; healed: string[];
};

/** Trim a check to what the UI actually reads back.
 *  MEASURED: 480 checks x ~300B = ~144KB per deep exchange, and `draft` stored a second full copy
 *  of the same matrix — 12 threads came to 5.52MB and blew the ~5MB quota outright. The drawer
 *  needs the quote, the tooltip needs the reason; neither needs 300 characters of them. */
const packCheck = (c: ClaimCheck) => ({
  sentence_id: c.sentence_id, source_id: c.source_id, claim_id: c.claim_id,
  verdict: c.verdict, iteration: c.iteration,
  quote: c.quote ? c.quote.slice(0, 110) : null,
  reason: (c.reason ?? "").slice(0, 110),
  quote_start: c.quote_start, quote_end: c.quote_end, confidence: c.confidence,
});

/** The first-draft view only needs the verdict per cell — never the evidence. */
const packDraft = (c: ClaimCheck) => ({
  sentence_id: c.sentence_id, source_id: c.source_id, claim_id: c.claim_id,
  verdict: c.verdict, iteration: c.iteration,
  quote: null, reason: "", quote_start: null, quote_end: null, confidence: c.confidence,
});

const mapValues = <T, R>(o: Record<string, T>, f: (v: T) => R): Record<string, R> =>
  Object.fromEntries(Object.entries(o).map(([k, v]) => [k, f(v)]));

/** Serialize a thread. `slim` additionally sheds what is only interesting live.
 *
 *  What must survive is what makes a reopened answer readable and auditable: the text, the marks,
 *  the matrix, the withdrawals, the tally. Per-agent tool traces are already told by the activity
 *  log, so they are never stored. */
const encode = (t: Thread, slim = false) => ({
  ...t,
  exchanges: t.exchanges.map((ex) => ({
    ...ex,
    repairing: [] as string[],       // transient by definition — nothing is mid-repair on disk
    healed: [...ex.healed],
    // A run cut off by a reload is not "done" — it stopped, and it says so.
    phase: ex.phase === "done" || ex.phase === "error" ? ex.phase : "interrupted",
    checks: mapValues(ex.checks, packCheck),
    draft: mapValues(ex.draft, packDraft),
    log: ex.log.slice(slim ? -120 : -260),
    claimsBy: slim ? {} : ex.claimsBy,
    // Tool traces are live-only; the activity log already records every call.
    researchers: mapValues(ex.researchers, (r) => ({ ...r, tools: [] })),
    graph: slim ? null : ex.graph,
  })),
});

const decode = (t: any): Thread => ({
  ...t,
  exchanges: (t.exchanges ?? []).map((ex: StoredExchange) => ({
    ...ex,
    repairing: new Set(ex.repairing ?? []),
    healed: new Set(ex.healed ?? []),
    // Threads saved by an older build predate these fields. A restored thread must never be a
    // shape the components have not seen — default every collection rather than trusting the blob.
    log: ex.log ?? [],
    notes: ex.notes ?? [],
    conflicts: ex.conflicts ?? [],
    retracted: ex.retracted ?? [],
    gaps: ex.gaps ?? [],
    artifacts: ex.artifacts ?? [],
    sources: ex.sources ?? {},
    checks: ex.checks ?? {},
    draft: ex.draft ?? {},
    researchers: ex.researchers ?? {},
    order: ex.order ?? [],
    ledger: ex.ledger ?? { rows: [], cols: [] },
    answer: ex.answer ?? { text: "", sentences: [] },
  })),
});

function loadThreads(): Thread[] {
  try {
    // Escape hatch: ?reset clears everything. If a store ever does wedge the page on boot, this
    // is the only way back in without opening devtools.
    if (typeof location !== "undefined" && /[?&]reset\b/.test(location.search)) {
      localStorage.removeItem(LS_KEY);
      return [];
    }
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return [];

    // Parsing happens before the first paint, synchronously, on the main thread. An oversized
    // blob (deep runs are ~460KB each) turns startup into megabytes of allocation and can take
    // the tab down with it — "Aw, snap" on load, before anything has rendered. Cheap to check the
    // length first; a truncated history beats a page that will not open.
    if (raw.length > MAX_STORE_BYTES) {
      const trimmed = (JSON.parse(raw) as any[]).slice(0, 2);
      localStorage.setItem(LS_KEY, JSON.stringify(trimmed));
      return trimmed.map(decode);
    }

    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.map(decode) : [];
  } catch {
    // A corrupt or unparseable store must never white-screen the app. Drop it and move on.
    try { localStorage.removeItem(LS_KEY); } catch { /* ignore */ }
    return [];
  }
}

/** Persist, degrading rather than destroying.
 *
 *  The previous version ended its retry loop with removeItem(): one oversized deep run and the
 *  ENTIRE history was wiped — the user watched their threads disappear. Losing the oldest thread
 *  to make room is a trade-off; losing all of them is data loss. So: try full, then slim, then
 *  fewer, and if even one thread will not fit, keep whatever was already stored. */
function saveThreads(threads: Thread[], preferSlim = false): void {
  const keep = [...threads]
    .filter((t) => t.exchanges.length)
    .sort((a, b) => b.updated - a.updated)
    .slice(0, MAX_THREADS);
  if (!keep.length) return;

  for (const slim of preferSlim ? [true] : [false, true]) {
    for (let n = keep.length; n > 0; n--) {
      try {
        localStorage.setItem(LS_KEY, JSON.stringify(keep.slice(0, n).map((t) => encode(t, slim))));
        return;
      } catch {
        // over quota — shed the oldest and try again, then try again slimmer
      }
    }
  }
  // Nothing fit. Leave the last good store alone: stale history beats no history.
}

/** Save soon, but rarely, and cheaply while a run is hot.
 *
 *  Saving only on `done` meant a thread existed nowhere but memory for the entire run — reload
 *  while researching and the conversation was gone. But the first fix over-corrected: a 3s
 *  debounce re-serialized the WHOLE store ~20x a minute, and JSON.stringify + localStorage are
 *  both synchronous and main-thread. A deep run is multiple MB and lasts ~50 minutes, so the tab
 *  spent the run allocating and writing megabytes on top of ~10 events/sec of state churn — which
 *  is what crashed it ("Aw, snap"). So: a long window, and the slim shape while running (the
 *  in-flight snapshot only has to survive a reload, and a resumed run rebuilds the rest anyway). */
const SAVE_EVERY_MS = 15000;
let saveTimer: ReturnType<typeof setTimeout> | null = null;

function scheduleSave(): void {
  if (saveTimer) return;
  saveTimer = setTimeout(() => {
    saveTimer = null;
    try {
      const threads = useChat.getState().threads;
      const hot = threads.some((t) =>
        t.exchanges.some((e) => e.phase !== "done" && e.phase !== "error" && e.phase !== "interrupted"));
      saveThreads(threads, hot);
    } catch { /* never break a run over a save */ }
  }, SAVE_EVERY_MS);
}

const newThreadId = () => `t${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

/** Append to the run log. A deep run emits ~500 checks; the log is the honest record of them, but
 *  it is also persisted, so it is bounded. The head is kept because that is where planning and
 *  retrieval live — dropping it would make a reopened thread look like it began mid-check. */
const LOG_HEAD = 60;
const LOG_TAIL = 340;

function note(ex: Exchange, kind: LogKind, what: string, who?: string, detail?: string): LogEntry[] {
  const entry: LogEntry = { t: Date.now() - ex.startedAt, kind, what, who, detail };
  const log = [...ex.log, entry];
  if (log.length <= LOG_HEAD + LOG_TAIL) return log;
  return [...log.slice(0, LOG_HEAD), ...log.slice(-LOG_TAIL)];
}

const short = (u: string) => u.replace(/^https?:\/\/(www\.)?/, "").slice(0, 46);

function freshExchange(question: string, mode: string): Exchange {
  return {
    key: `x${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
    queryId: null, question, mode, cacheMode: "auto", kind: "research", phase: "researching",
    startedAt: Date.now(), elapsed: 0,
    researchers: {}, order: [], sources: {},
    checks: {}, draft: {}, repairing: new Set(), healed: new Set(),
    log: [], claimsBy: {}, lastAt: Date.now(),
    ledger: { rows: [], cols: [] },
    answer: { text: "", sentences: [] },
    gaps: [], conflicts: [], retracted: [], trust: null, notes: [],
    graph: null, artifacts: [],
  };
}

const booted = loadThreads();

export const useChat = create<ChatState>((set, get) => ({
  threads: booted,
  activeId: booted[0]?.id ?? "",
  showDraft: {},
  openSource: null,
  focusSentence: null,
  workspaces: [],
  activeWorkspace: null,
  storeEnabled: false,

  newThread: () => set({ activeId: "", openSource: null, focusSentence: null }),
  openThread: (id) => set({ activeId: id, openSource: null, focusSentence: null }),
  deleteThread: (id) =>
    set((s) => {
      const threads = s.threads.filter((t) => t.id !== id);
      saveThreads(threads);
      return { threads, activeId: s.activeId === id ? (threads[0]?.id ?? "") : s.activeId };
    }),

  async loadWorkspaces() {
    try {
      const res = await fetch("/api/workspaces");
      if (!res.ok) { set({ storeEnabled: false }); return; }   // 503 => feature off
      const { workspaces } = await res.json();
      set({ storeEnabled: true, workspaces: workspaces ?? [] });
    } catch { set({ storeEnabled: false }); }
  },

  async createWorkspace(title) {
    try {
      const res = await fetch("/api/workspaces", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      if (!res.ok) return null;
      const { workspace } = await res.json();
      set((s) => ({ workspaces: [workspace, ...s.workspaces], activeWorkspace: workspace.slug }));
      return workspace.slug as string;
    } catch { return null; }
  },

  setActiveWorkspace(slug) { set({ activeWorkspace: slug }); },

  async deleteWorkspace(slug) {
    try { await fetch(`/api/workspaces/${slug}`, { method: "DELETE" }); } catch { /* ignore */ }
    set((s) => ({
      workspaces: s.workspaces.filter((w) => w.slug !== slug),
      activeWorkspace: s.activeWorkspace === slug ? null : s.activeWorkspace,
    }));
  },

  async ingestFiles(files) {
    const slug = get().activeWorkspace;
    if (!slug || !files.length) return null;
    const form = new FormData();
    for (const f of files) form.append("files", f, f.name);
    try {
      const res = await fetch(`/api/workspaces/${slug}/ingest`, { method: "POST", body: form });
      if (!res.ok) return null;
      const summary = await res.json();
      await get().loadWorkspaces();   // refresh doc/chunk counts
      return summary;
    } catch { return null; }
  },

  async ask(question, mode) {
    const ex = freshExchange(question, mode);

    // A question always lands in the active thread; asking with none open starts one. The thread
    // is titled by its opening question — that is all the sidebar needs to be legible.
    let threadId = get().activeId;
    set((s) => {
      const existing = s.threads.find((t) => t.id === s.activeId);
      if (existing) {
        return {
          threads: s.threads.map((t) =>
            t.id === existing.id
              ? { ...t, exchanges: [...t.exchanges, ex], updated: Date.now() }
              : t,
          ),
        };
      }
      threadId = newThreadId();
      const t: Thread = {
        id: threadId, title: question.trim().slice(0, 120),
        created: Date.now(), updated: Date.now(), exchanges: [ex],
      };
      return { threads: [t, ...s.threads], activeId: threadId };
    });
    // Write it out immediately: a reload one second later must not lose the question.
    saveThreads(get().threads);

    // Follow-ups need what came before, or "what about the paid tier?" researches nothing.
    const history = (get().threads.find((t) => t.id === threadId)?.exchanges ?? [])
      .filter((e) => e.key !== ex.key && e.answer.text)
      .slice(-3)
      .map((e) => ({ question: e.question, answer: e.answer.text.slice(0, 1500) }));

    const workspace = get().activeWorkspace;
    if (workspace) patch(set, ex.key, () => ({ workspace }));
    try {
      const res = await fetch("/api/research", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, mode, history, workspace }),
      });
      if (!res.ok) throw new Error(`start failed: HTTP ${res.status}`);
      const { query_id } = await res.json();
      patch(set, ex.key, () => ({ queryId: query_id }));
      get().listen(ex.key, query_id);
    } catch (e: any) {
      patch(set, ex.key, () => ({
        phase: "error" as RunPhase,
        notes: [{ scope: "run", message: String(e?.message ?? e) }],
      }));
    }
  },

  /** Attach to a run. Safe to call on a run already in flight — the server runs each query_id
   *  exactly once and replays its buffer to whoever attaches, so this resumes rather than
   *  restarts. That is what makes a reload continue instead of researching all over again. */
  listen(exKey, queryId) {
    try {
      const es = new EventSource(`/api/research/stream?query_id=${queryId}`);
      const forward = (event: string) =>
        es.addEventListener(event, (m: MessageEvent) => {
          // One malformed frame must not throw out of the listener and kill the run. Parse once,
          // defensively: a stream that hiccups should cost one event, not the whole answer.
          let d: any;
          try {
            d = JSON.parse(m.data);
          } catch {
            return;
          }
          get().apply(exKey, event, d);
          if (event === "done" || (event === "error" && d?.scope === "run")) es.close();
        });
      [
        "meta", "route", "plan", "agent_status", "agent_tool", "source", "agent_token", "agent_answer",
        "claims", "verdict", "rewrite_start", "rewrite_done", "agent_report", "lead_token",
        "heatmap", "trust", "contradiction", "answer_done", "graph", "artifact", "provider",
        "error", "done",
      ].forEach(forward);
      es.onerror = () => {
        // EventSource retries on its own, and reattaching is now safe (the server replays rather
        // than re-runs), so a blip costs nothing. Only close once the run is actually finished.
        const cur = get().threads.flatMap((t) => t.exchanges).find((e) => e.key === exKey);
        if (cur && cur.phase !== "done" && cur.phase !== "error") return;
        es.close();
      };
    } catch (e: any) {
      patch(set, exKey, () => ({
        phase: "error" as RunPhase,
        notes: [{ scope: "run", message: String(e?.message ?? e) }],
      }));
    }
  },

  /** On boot, re-attach to anything that was still running. The server kept the run going and
   *  buffered every event, so this replays what was missed and then follows live — the reload
   *  costs nothing and re-researches nothing. */
  reattach() {
    for (const ex of get().threads.flatMap((t) => t.exchanges)) {
      if (ex.queryId && (ex.phase === "interrupted" || ex.phase === "researching" ||
                         ex.phase === "checking" || ex.phase === "repairing" || ex.phase === "writing")) {
        patch(set, ex.key, () => ({ phase: "researching" as RunPhase, log: [], checks: {}, draft: {} }));
        get().listen(ex.key, ex.queryId);
      }
    }
  },

  async stop(exKey) {
    const ex = get().threads.flatMap((t) => t.exchanges).find((e) => e.key === exKey);
    if (!ex?.queryId) return;
    try {
      await fetch(`/api/research/${ex.queryId}/stop`, { method: "POST" });
    } catch { /* the run ending is what matters; a failed stop call is not worth a dialog */ }
    patch(set, exKey, () => ({ phase: "done" as RunPhase }));
    saveThreads(get().threads);
  },

  /** Re-run an interrupted or failed exchange in place. Most of its work is already cached, so
   *  this is usually far cheaper than the first attempt. */
  async retry(exKey) {
    const ex = get().threads.flatMap((t) => t.exchanges).find((e) => e.key === exKey);
    if (!ex) return;
    set((s) => ({
      threads: s.threads.map((t) => ({
        ...t,
        exchanges: t.exchanges.filter((e) => e.key !== exKey),
      })),
    }));
    await get().ask(ex.question, ex.mode);
  },

  apply(exKey, event, d) {
    // A structural event (verdict, agent_answer, answer_done, done…) must see the streamed text
    // already applied, so drain the token buffer for this exchange first.
    if (event !== "agent_token" && event !== "lead_token") flushTokensFor(exKey);
    switch (event) {
      case "meta":
        return patch(set, exKey, () => ({
          cacheMode: d.mode,
          resolvedMode: d.search_mode,          // what auto-mode actually picked
          workspace: d.workspace ?? null,
        }));

      case "route":
        return patch(set, exKey, (ex) => ({
          kind: d.kind === "task" ? "task" : "research",
          routeTitle: d.title,
          // A task run does no research and no fact-checking; a plain draft phase reads right.
          phase: d.kind === "task" ? ("writing" as RunPhase) : ex.phase,
          log: note(
            ex,
            d.kind === "task" ? "report" : "plan",
            d.kind === "task" ? `task detected — ${d.title ?? "doing it"}` : "research question",
            undefined,
            d.reason,
          ),
        }));

      case "plan":
        return patch(set, exKey, (ex) => {
          const researchers: Record<string, Researcher> = {};
          const order: string[] = [];
          let log = note(ex, "plan", `split into ${d.subtasks.length} sub-questions`);
          for (const t of d.subtasks) {
            researchers[t.agent_id] = blankResearcher(t.agent_id, t.title);
            order.push(t.agent_id);
            log = note({ ...ex, log }, "plan", t.title, t.agent_id, t.lane);
          }
          return { researchers, order, log };
        });

      case "agent_status":
        return patch(set, exKey, (ex) => {
          const r = ex.researchers[d.agent_id] ?? blankResearcher(d.agent_id);
          const phase: RunPhase =
            d.status === "rewriting" ? "repairing"
            : d.status === "verifying" ? "checking"
            : ex.phase;
          return {
            phase,
            researchers: { ...ex.researchers, [d.agent_id]: { ...r, status: d.status, detail: d.detail } },
          };
        });

      case "agent_tool":
        return patch(set, exKey, (ex) => {
          const r = ex.researchers[d.agent_id] ?? blankResearcher(d.agent_id);
          const tools = [...r.tools];
          const i = tools.findIndex((t) => t.call_id === d.call_id && t.args === d.args_preview);
          const row = { call_id: d.call_id, tool: d.tool, args: d.args_preview, status: d.status, ms: d.ms };
          if (i >= 0) tools[i] = row; else tools.push(row);
          // Log the call once, when it is first seen — later frames only update its status.
          let log = ex.log;
          if (i < 0) {
            let arg = d.args_preview ?? "";
            try { const o = JSON.parse(arg); arg = o.query ?? o.url ?? arg; } catch { /* bare */ }
            log = d.tool === "web_search"
              ? note(ex, "search", `“${String(arg).slice(0, 52)}”`, d.agent_id)
              : note(ex, "read", short(String(arg)), d.agent_id);
          }
          return { researchers: { ...ex.researchers, [d.agent_id]: { ...r, tools } }, log };
        });

      case "source":
        return patch(set, exKey, (ex) => ({
          sources: { ...ex.sources, [d.id]: d },
          log: ex.sources[d.id]
            ? ex.log
            : note(ex, "read", `source [${d.id}] ${d.domain}`, d.first_agent,
                   `${Number(d.n_chars ?? 0).toLocaleString()} chars`),
        }));

      case "agent_token":
        return bufferToken(exKey, d.agent_id, d.text);

      case "agent_answer":
        // Authoritative text — sentence offsets index into THIS string, never the token stream.
        return patch(set, exKey, (ex) => {
          const r = ex.researchers[d.agent_id] ?? blankResearcher(d.agent_id);
          const cited = (d.sentences ?? []).filter((s: SentenceRef) => s.cited?.length).length;
          let log = note(
            ex, "draft",
            d.iteration > 0 ? `redrafted after corrections` : `drafted ${(d.sentences ?? []).length} sentences`,
            d.agent_id, `${cited} cite sources`,
          );
          // An invented citation marker is a real catch — it must never pass silently.
          if (d.orphans?.length) {
            log = note({ ...ex, log }, "warn",
              `dropped ${d.orphans.length} invented citation marker${d.orphans.length > 1 ? "s" : ""}`,
              d.agent_id);
          }
          return {
            researchers: {
              ...ex.researchers,
              [d.agent_id]: {
                ...r, text: d.text, sentences: d.sentences,
                orphans: d.orphans ?? [], iteration: d.iteration,
              },
            },
            log,
          };
        });

      case "claims":
        return patch(set, exKey, (ex) => ({
          claimsBy: { ...ex.claimsBy, [d.agent_id]: d.claims ?? [] },
          log: note(ex, "claims", `${(d.claims ?? []).length} checkable claims extracted`, d.agent_id),
        }));

      case "lead_token":
        return bufferToken(exKey, null, d.text);

      case "verdict":
        return patch(set, exKey, (ex) => {
          const key = `${d.sentence_id}:${d.source_id}`;
          const check: ClaimCheck = {
            sentence_id: d.sentence_id, source_id: d.source_id, claim_id: d.claim_id,
            verdict: d.verdict as Verdict, quote: d.quote, quote_start: d.quote_start,
            quote_end: d.quote_end, confidence: d.confidence, reason: d.reason,
            iteration: d.iteration, downgraded: d.downgraded,
          };
          // Iteration 0 is frozen forever — it is the first-draft toggle.
          const draft = d.iteration === 0 && !ex.draft[key] ? { ...ex.draft, [key]: check } : ex.draft;
          const repairing = new Set(ex.repairing);
          const healed = new Set(ex.healed);
          if (d.iteration > 0) {
            repairing.delete(d.sentence_id);
            const before = ex.draft[key]?.verdict;
            if ((before === "unsupported" || before === "contradicted") &&
                (d.verdict === "supported" || d.verdict === "weak")) {
              healed.add(d.sentence_id);
            }
          }
          const kind: LogKind =
            d.verdict === "supported" ? "ok"
            : d.verdict === "weak" ? "weak"
            : d.verdict === "contradicted" ? "clash"
            : "bad";
          const who = String(d.sentence_id).split(".")[0];
          // The quote IS the evidence — show it when there is one, and the reason when there isn't.
          const detail = d.quote
            ? `“${String(d.quote).slice(0, 60)}”`
            : String(d.reason ?? "").slice(0, 60);
          const log = note(
            ex, kind,
            `${d.sentence_id} → [${d.source_id}]${d.iteration > 0 ? " (recheck)" : ""}`,
            who, detail,
          );
          return { checks: { ...ex.checks, [key]: check }, draft, repairing, healed, log };
        });

      case "rewrite_start":
        return patch(set, exKey, (ex) => {
          const repairing = new Set(ex.repairing);
          repairing.add(d.sentence_id);
          return {
            phase: "repairing" as RunPhase,
            repairing,
            log: note(ex, "fix", `rewriting ${d.sentence_id} against the source`,
                      String(d.sentence_id).split(".")[0], String(d.reason ?? "").slice(0, 60)),
          };
        });

      case "rewrite_done":
        return patch(set, exKey, (ex) => {
          const repairing = new Set(ex.repairing);
          repairing.delete(d.sentence_id);
          const who = String(d.sentence_id).split(".")[0];
          if (d.outcome !== "retracted") {
            return { repairing, log: note(ex, "fixed", `${d.sentence_id} rewritten`, who) };
          }
          const checks = { ...ex.checks };
          for (const k of Object.keys(checks)) {
            if (checks[k].sentence_id === d.sentence_id) {
              checks[k] = { ...checks[k], verdict: "retracted" };
            }
          }
          return {
            repairing, checks,
            log: note(ex, "drop", `${d.sentence_id} withdrawn — no supported version`, who),
          };
        });

      case "agent_report":
        return patch(set, exKey, (ex) => ({
          retracted: [...ex.retracted, ...(d.retracted ?? [])],
          log: note(ex, "draft", `${d.agent_id} finished`, d.agent_id,
                    d.trust ? `${d.trust.supported}/${d.trust.total} verified` : undefined),
        }));

      case "heatmap":
        return patch(set, exKey, () => ({ ledger: { rows: d.rows, cols: d.cols } }));

      case "trust":
        return d.scope === "final"
          ? patch(set, exKey, (ex) => ({
              trust: d,
              log: note(ex, "final", `${d.supported} of ${d.total} sentences verified`, undefined,
                        `${d.retracted} withdrawn · ${d.weak} thin`),
            }))
          : undefined;

      case "contradiction":
        return patch(set, exKey, (ex) => ({
          conflicts: [...ex.conflicts, d],
          log: note(ex, "clash", "sources disagree", undefined,
                    String(d.reason ?? "").slice(0, 60)),
        }));

      case "answer_done":
        return patch(set, exKey, (ex) => ({
          answer: { text: d.text, sentences: d.sentences },
          gaps: d.gaps ?? ex.gaps,
          log: note(ex, "merge", `final answer written`, "lead",
                    `${(d.sentences ?? []).length} sentences${d.gaps?.length ? ` · ${d.gaps.length} gaps stated` : ""}`),
        }));

      case "graph":
        return patch(set, exKey, (ex) => ({
          graph: { nodes: d.nodes ?? [], links: d.links ?? [] },
          log: note(ex, "graph", "provenance graph built", undefined,
                    `${(d.nodes ?? []).length} nodes · ${(d.links ?? []).length} links`),
        }));

      case "artifact":
        return patch(set, exKey, (ex) => ({
          artifacts: [...ex.artifacts, { id: d.id, name: d.name, url: d.url, kind: d.kind }],
          log: note(ex, "report", `audit report compiled`, "reporter", d.name),
        }));

      // A provider retrying is not a run failure — it is the reason for the silence. It goes in
      // the log verbatim, but never into `notes` (which is for things that changed the answer).
      case "provider":
        return patch(set, exKey, (ex) => ({
          log: note(ex, "warn", String(d.message ?? "provider trouble"), d.scope),
        }));

      case "error":
        return patch(set, exKey, (ex) => ({
          notes: [...ex.notes, d],
          log: note(ex, "warn", String(d.message ?? "").slice(0, 70), d.scope),
          ...(d.scope === "run" ? { phase: "error" as RunPhase } : {}),
        }));

      case "done":
        patch(set, exKey, (ex) => ({
          phase: "done" as RunPhase,
          elapsed: d.elapsed_s ?? (Date.now() - ex.startedAt) / 1000,
        }));
        // Persist only at rest. Saving on every verdict would re-serialize the whole history
        // hundreds of times per run.
        saveThreads(get().threads);
        return;
    }
  },

  toggleDraft: (exKey) =>
    set((s) => ({ showDraft: { ...s.showDraft, [exKey]: !s.showDraft[exKey] } })),
  viewSource: (exKey, id, quote) => set({ openSource: { exKey, id, quote } }),
  closeSource: () => set({ openSource: null }),
  focus: (sid) => set({ focusSentence: sid }),
}));

/** Update one exchange wherever it lives.
 *
 *  Keyed on exKey across ALL threads, never on the active one: a run keeps streaming after you
 *  switch away, and writing its verdicts into whichever thread happens to be open would corrupt
 *  a finished answer with another question's marks. */
// ——— token coalescing ———————————————————————————————————————————————
// agent_token / lead_token arrive per token — tens of thousands over a long run. Patching the whole
// thread tree on every one pegged the main thread until Safari killed the tab. Buffer the appends
// and flush at ~12 Hz: identical text on screen, a fraction of the renders. Any structural event
// flushes first (see apply), so ordering is preserved.
type TokBuf = { agent: Record<string, string>; lead: string };
const tokenBuf = new Map<string, TokBuf>();
let tokenTimer: ReturnType<typeof setTimeout> | null = null;

function bufferToken(exKey: string, agent: string | null, text: string) {
  let b = tokenBuf.get(exKey);
  if (!b) { b = { agent: {}, lead: "" }; tokenBuf.set(exKey, b); }
  if (agent) b.agent[agent] = (b.agent[agent] ?? "") + text;
  else b.lead += text;
  if (tokenTimer == null) tokenTimer = setTimeout(flushTokens, 80);
}

function flushOne(exKey: string, b: TokBuf) {
  patch(useChat.setState, exKey, (ex) => {
    const out: Partial<Exchange> = {};
    const aids = Object.keys(b.agent);
    if (aids.length) {
      const researchers = { ...ex.researchers };
      for (const aid of aids) {
        const r = researchers[aid] ?? blankResearcher(aid);
        researchers[aid] = { ...r, text: r.text + b.agent[aid] };
      }
      out.researchers = researchers;
    }
    if (b.lead) {
      out.answer = { ...ex.answer, text: ex.answer.text + b.lead };
      out.phase = "writing" as RunPhase;
      if (!ex.answer.text) {
        out.log = note(ex, "merge", "merging findings into one answer", "lead",
                       "cannot see source text — cites only what was read");
      }
    }
    return out;
  });
}

function flushTokens() {
  tokenTimer = null;
  for (const [exKey, b] of tokenBuf) flushOne(exKey, b);
  tokenBuf.clear();
}

function flushTokensFor(exKey: string) {
  const b = tokenBuf.get(exKey);
  if (!b) return;
  tokenBuf.delete(exKey);
  flushOne(exKey, b);
}

function patch(
  set: (fn: (s: ChatState) => Partial<ChatState>) => void,
  exKey: string,
  fn: (ex: Exchange) => Partial<Exchange> | undefined,
) {
  set((s) => {
    let hit = false;
    const threads = s.threads.map((t) => {
      if (!t.exchanges.some((e) => e.key === exKey)) return t;
      hit = true;
      return {
        ...t,
        updated: Date.now(),
        exchanges: t.exchanges.map((ex) => {
          if (ex.key !== exKey) return ex;
          const p = fn(ex);
          if (!p) return ex;
          // Any event at all is proof of life; stamp it so the UI can show a stall honestly.
          return { ...ex, ...p, lastAt: Date.now() };
        }),
      };
    });
    if (hit) scheduleSave();
    return hit ? { threads } : {};
  });
}

export const checkKey = (sid: string, srcId: number) => `${sid}:${srcId}`;
