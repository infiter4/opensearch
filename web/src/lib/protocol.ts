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

/** The desk's vocabulary. Glyph + short label for the tally and the grid; `note` is what a
 *  reader sees on hover — plain English, no jargon. */
export const MARK: Record<Verdict, { word: string; glyph: string; note: string }> = {
  supported: { word: "verified", glyph: "✓", note: "the source says this" },
  weak: { word: "thin sourcing", glyph: "◐", note: "true, but on one weak source" },
  unsupported: { word: "unsupported, kept", glyph: "?", note: "the cited page never says this" },
  contradicted: { word: "contradicted", glyph: "✕", note: "the cited page says the opposite" },
  retracted: { word: "withdrawn, shown", glyph: "⊘", note: "no honest version survived — withdrawn, not hidden" },
  pending: { word: "at the desk", glyph: "·", note: "being cross-examined" },
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
