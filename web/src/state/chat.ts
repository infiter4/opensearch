import { create } from "zustand";
import type {
  ClaimCheck, LedgerRow, Researcher, Retraction, SentenceRef, SourceInfo, TrustTally, Verdict,
} from "../lib/protocol";

export type RunPhase = "researching" | "checking" | "repairing" | "writing" | "done" | "error";

export interface Exchange {
  key: string;               // client-side key, stable for React
  queryId: string | null;    // server session id, from the POST + meta
  question: string;
  mode: string;              // lite | pro | deep
  cacheMode: string;         // live | auto | replay
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

interface ChatState {
  exchanges: Exchange[];
  showDraft: Record<string, boolean>;   // per-exchange first-draft toggle
  openSource: { exKey: string; id: number; quote?: string | null } | null;
  focusSentence: string | null;

  ask(question: string, mode: string): Promise<void>;
  apply(exKey: string, event: string, d: any): void;
  toggleDraft(exKey: string): void;
  viewSource(exKey: string, id: number, quote?: string | null): void;
  closeSource(): void;
  focus(sid: string | null): void;
}

const blankResearcher = (id: string, title = ""): Researcher => ({
  id, title, status: "spawned", text: "", sentences: [], orphans: [], iteration: 0, tools: [],
});

function freshExchange(question: string, mode: string): Exchange {
  return {
    key: `x${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
    queryId: null, question, mode, cacheMode: "auto", phase: "researching",
    startedAt: Date.now(), elapsed: 0,
    researchers: {}, order: [], sources: {},
    checks: {}, draft: {}, repairing: new Set(), healed: new Set(),
    ledger: { rows: [], cols: [] },
    answer: { text: "", sentences: [] },
    gaps: [], conflicts: [], retracted: [], trust: null, notes: [],
    graph: null, artifacts: [],
  };
}

export const useChat = create<ChatState>((set, get) => ({
  exchanges: [],
  showDraft: {},
  openSource: null,
  focusSentence: null,

  async ask(question, mode) {
    const ex = freshExchange(question, mode);
    set((s) => ({ exchanges: [...s.exchanges, ex] }));

    try {
      const res = await fetch("/api/research", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, mode }),
      });
      if (!res.ok) throw new Error(`start failed: HTTP ${res.status}`);
      const { query_id } = await res.json();
      patch(set, ex.key, () => ({ queryId: query_id }));

      const es = new EventSource(`/api/research/stream?query_id=${query_id}`);
      const forward = (event: string) =>
        es.addEventListener(event, (m: MessageEvent) => {
          get().apply(ex.key, event, JSON.parse(m.data));
          if (event === "done" || (event === "error" && JSON.parse(m.data).scope === "run")) es.close();
        });
      [
        "meta", "plan", "agent_status", "agent_tool", "source", "agent_token", "agent_answer",
        "claims", "verdict", "rewrite_start", "rewrite_done", "agent_report", "lead_token",
        "heatmap", "trust", "contradiction", "answer_done", "graph", "artifact", "error", "done",
      ].forEach(forward);
      es.onerror = () => {
        // EventSource retries on its own; only a closed+errored stream on a finished run matters.
        const cur = get().exchanges.find((e) => e.key === ex.key);
        if (cur && cur.phase !== "done") return;
        es.close();
      };
    } catch (e: any) {
      patch(set, ex.key, () => ({
        phase: "error" as RunPhase,
        notes: [{ scope: "run", message: String(e?.message ?? e) }],
      }));
    }
  },

  apply(exKey, event, d) {
    switch (event) {
      case "meta":
        return patch(set, exKey, () => ({ cacheMode: d.mode }));

      case "plan":
        return patch(set, exKey, () => {
          const researchers: Record<string, Researcher> = {};
          const order: string[] = [];
          for (const t of d.subtasks) {
            researchers[t.agent_id] = blankResearcher(t.agent_id, t.title);
            order.push(t.agent_id);
          }
          return { researchers, order };
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
          return { researchers: { ...ex.researchers, [d.agent_id]: { ...r, tools } } };
        });

      case "source":
        return patch(set, exKey, (ex) => ({ sources: { ...ex.sources, [d.id]: d } }));

      case "agent_token":
        return patch(set, exKey, (ex) => {
          const r = ex.researchers[d.agent_id] ?? blankResearcher(d.agent_id);
          return { researchers: { ...ex.researchers, [d.agent_id]: { ...r, text: r.text + d.text } } };
        });

      case "agent_answer":
        // Authoritative text — sentence offsets index into THIS string, never the token stream.
        return patch(set, exKey, (ex) => {
          const r = ex.researchers[d.agent_id] ?? blankResearcher(d.agent_id);
          return {
            researchers: {
              ...ex.researchers,
              [d.agent_id]: {
                ...r, text: d.text, sentences: d.sentences,
                orphans: d.orphans ?? [], iteration: d.iteration,
              },
            },
          };
        });

      case "lead_token":
        return patch(set, exKey, (ex) => ({
          phase: "writing" as RunPhase,
          answer: { ...ex.answer, text: ex.answer.text + d.text },
        }));

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
          return { checks: { ...ex.checks, [key]: check }, draft, repairing, healed };
        });

      case "rewrite_start":
        return patch(set, exKey, (ex) => {
          const repairing = new Set(ex.repairing);
          repairing.add(d.sentence_id);
          return { phase: "repairing" as RunPhase, repairing };
        });

      case "rewrite_done":
        return patch(set, exKey, (ex) => {
          const repairing = new Set(ex.repairing);
          repairing.delete(d.sentence_id);
          if (d.outcome !== "retracted") return { repairing };
          const checks = { ...ex.checks };
          for (const k of Object.keys(checks)) {
            if (checks[k].sentence_id === d.sentence_id) {
              checks[k] = { ...checks[k], verdict: "retracted" };
            }
          }
          return { repairing, checks };
        });

      case "agent_report":
        return patch(set, exKey, (ex) => ({
          retracted: [...ex.retracted, ...(d.retracted ?? [])],
        }));

      case "heatmap":
        return patch(set, exKey, () => ({ ledger: { rows: d.rows, cols: d.cols } }));

      case "trust":
        return d.scope === "final" ? patch(set, exKey, () => ({ trust: d })) : undefined;

      case "contradiction":
        return patch(set, exKey, (ex) => ({ conflicts: [...ex.conflicts, d] }));

      case "answer_done":
        return patch(set, exKey, (ex) => ({
          answer: { text: d.text, sentences: d.sentences },
          gaps: d.gaps ?? ex.gaps,
        }));

      case "graph":
        return patch(set, exKey, () => ({ graph: { nodes: d.nodes ?? [], links: d.links ?? [] } }));

      case "artifact":
        return patch(set, exKey, (ex) => ({
          artifacts: [...ex.artifacts, { id: d.id, name: d.name, url: d.url, kind: d.kind }],
        }));

      case "error":
        return patch(set, exKey, (ex) => ({
          notes: [...ex.notes, d],
          ...(d.scope === "run" ? { phase: "error" as RunPhase } : {}),
        }));

      case "done":
        return patch(set, exKey, (ex) => ({
          phase: "done" as RunPhase,
          elapsed: d.elapsed_s ?? (Date.now() - ex.startedAt) / 1000,
        }));
    }
  },

  toggleDraft: (exKey) =>
    set((s) => ({ showDraft: { ...s.showDraft, [exKey]: !s.showDraft[exKey] } })),
  viewSource: (exKey, id, quote) => set({ openSource: { exKey, id, quote } }),
  closeSource: () => set({ openSource: null }),
  focus: (sid) => set({ focusSentence: sid }),
}));

function patch(
  set: (fn: (s: ChatState) => Partial<ChatState>) => void,
  exKey: string,
  fn: (ex: Exchange) => Partial<Exchange> | undefined,
) {
  set((s) => ({
    exchanges: s.exchanges.map((ex) => {
      if (ex.key !== exKey) return ex;
      const p = fn(ex);
      return p ? { ...ex, ...p } : ex;
    }),
  }));
}

export const checkKey = (sid: string, srcId: number) => `${sid}:${srcId}`;
