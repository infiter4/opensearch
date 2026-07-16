/** Wire types for the backend's SSE stream. Names mirror the events one-to-one. */

export type Verdict =
  | "supported" | "weak" | "unsupported" | "contradicted" | "retracted" | "pending";

/** Lower = worse. A sentence wears the worst mark any of its claims earned. */
const RANK: Record<Verdict, number> = {
  contradicted: 0, unsupported: 1, retracted: 2, weak: 3, supported: 4, pending: 9,
};

export function worstOf(vs: Verdict[]): Verdict {
  let out: Verdict = "pending";
  for (const v of vs) if (RANK[v] < RANK[out]) out = v;
  return out;
}

/** Verdict vocabulary. Glyph + short label for the summary and the matrix; `note` is what a
 *  reader sees on hover — plain English, no jargon. */
export const MARK: Record<Verdict, { word: string; glyph: string; note: string }> = {
  supported: { word: "verified", glyph: "✓", note: "the cited source states this" },
  weak: { word: "weakly supported", glyph: "◐", note: "supported, but only thinly" },
  unsupported: { word: "unsupported", glyph: "?", note: "the cited page never says this" },
  contradicted: { word: "contradicted", glyph: "✕", note: "the cited page says the opposite" },
  retracted: { word: "withdrawn", glyph: "⊘", note: "no supported version survived — withdrawn, not hidden" },
  pending: { word: "checking", glyph: "·", note: "being checked against its source" },
};

export interface SentenceRef { id: string; start: number; end: number; cited: number[] }

export interface SourceInfo {
  id: number; url: string; title: string; domain: string;
  n_chars?: number; first_agent?: string; lane?: string;
}

export interface ClaimCheck {
  sentence_id: string; source_id: number; claim_id: string;
  verdict: Verdict; quote: string | null; quote_start: number | null; quote_end: number | null;
  confidence: number; reason: string; iteration: number; downgraded?: boolean;
}

export interface ToolCall { call_id: string; tool: string; args: string; status: string; ms?: number }

export interface Researcher {
  id: string; title: string; status: string; detail?: string;
  text: string; sentences: SentenceRef[]; orphans: number[];
  iteration: number; tools: ToolCall[];
}

export interface LedgerRow {
  sentence_id: string; agent_id: string; text: string; order: number;
  band?: string; retracted?: boolean; reason?: string | null;
}

export interface TrustTally {
  scope: string; supported: number; weak: number; unsupported: number;
  contradicted: number; retracted: number; total: number; score: number;
}

export interface Retraction { sentence_id: string; text: string; reason: string }

/** One line of the run log.
 *
 *  Recorded when the event ARRIVES, never rebuilt at render time. The old activity view derived
 *  itself from the tool list on every render, so every line carried the render clock — the whole
 *  run stamped `:00` — and any stage that was not a tool call (planning, claim extraction,
 *  checking, correcting, merging) simply never appeared. */
export interface LogEntry {
  t: number;          // ms since the run started
  kind: LogKind;
  who?: string;       // agent id
  what: string;
  detail?: string;    // dim trailing text
}

export type LogKind =
  | "plan" | "search" | "read" | "draft" | "claims"
  | "ok" | "weak" | "bad" | "clash"
  | "fix" | "fixed" | "drop"
  | "merge" | "final" | "graph" | "report" | "warn";

/** Symbol per stage. Shape carries the meaning, not colour — the same rule the marks follow. */
export const LOG_GLYPH: Record<LogKind, string> = {
  plan: "◆", search: "⌕", read: "▤", draft: "✎", claims: "⊞",
  ok: "✓", weak: "◐", bad: "?", clash: "✕",
  fix: "↻", fixed: "✓", drop: "⊘",
  merge: "⋈", final: "▮", graph: "⬡", report: "▣", warn: "!",
};

/** Tally a set of checks the way the backend's `trust` does: worst-wins, once per SENTENCE.
 *
 *  Only used to rewind the summary to iteration 0. The final tally always comes from the backend's
 *  `trust` event — it is authoritative and must not be recomputed here. But no draft trust is ever
 *  emitted, and showing the FINAL numbers under a "first draft" heading states a falsehood about
 *  the one gesture the whole pitch rests on. Iteration-0 verdicts are real verdicts the client
 *  already holds; counting them is a view, not a second opinion.
 *
 *  `retracted` is deliberately NOT passed when rewinding: at iteration 0 nothing had been
 *  withdrawn yet, so those sentences count as whatever the checker actually said about them then.
 */
export function tallyOf(
  checks: ClaimCheck[],
  scope = "draft",
  retracted: Set<string> = new Set(),
): TrustTally {
  const bySent = new Map<string, Verdict[]>();
  for (const c of checks) {
    if (!bySent.has(c.sentence_id)) bySent.set(c.sentence_id, []);
    bySent.get(c.sentence_id)!.push(c.verdict);
  }
  const counts = { supported: 0, weak: 0, unsupported: 0, contradicted: 0, retracted: 0 };
  for (const [sid, vs] of bySent) {
    if (retracted.has(sid)) continue;
    const w = worstOf(vs);
    if (w in counts) counts[w as keyof typeof counts] += 1;
  }
  counts.retracted += retracted.size;
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const score = total ? (counts.supported + 0.5 * counts.weak) / total : 0;
  return { scope, ...counts, total, score: Math.round(score * 1000) / 1000 };
}
