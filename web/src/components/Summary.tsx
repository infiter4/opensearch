import { MARK, tallyOf, type Verdict } from "../lib/protocol";
import type { Exchange } from "../state/chat";

/* Verification summary: what held up, what didn't, and the arithmetic between them.
   Every number is derived from real verdicts; nothing is a model's self-assessment. */

const ORDER: Verdict[] = ["supported", "weak", "unsupported", "contradicted", "retracted"];

export function Summary({ ex, draft }: { ex: Exchange; draft: boolean }) {
  // Rewound, the panel must report iteration 0 — the final numbers under a "first draft" heading
  // would describe copy the reader is not looking at. Nothing was withdrawn yet at iteration 0,
  // so no retracted set is passed.
  const t = draft ? tallyOf(Object.values(ex.draft)) : ex.trust;
  if (!t) return null;

  const counts: Record<Verdict, number> = {
    supported: t.supported, weak: t.weak, unsupported: t.unsupported,
    contradicted: t.contradicted, retracted: t.retracted, pending: 0,
  };
  const quotes = Object.values(draft ? ex.draft : ex.checks).filter((c) => c.quote).length;
  const nSources = Object.keys(ex.sources).length;

  return (
    <div>
      <div className="label rule-b pb-1.5 mb-3">
        {draft ? "before verification" : "verification"}
      </div>

      <div className="flex items-baseline gap-2">
        <span className={`text-[38px] leading-none ${draft ? "text-amber" : ""}`}>{t.supported}</span>
        <span className="text-slate text-[20px]">/ {t.total}</span>
      </div>
      <div className="text-[13px] text-slate mt-1.5 leading-snug">
        sentences verified against their sources
      </div>

      <div className="mt-4 space-y-1">
        {ORDER.map((v) => (
          <div key={v} className="flex items-baseline gap-2 font-mono text-[11px]" data-note={MARK[v].note}>
            <span className={v === "contradicted" || v === "retracted" ? "text-amber w-3" : "text-slate w-3"}>
              {MARK[v].glyph}
            </span>
            <span className="text-paper/75 flex-1">{MARK[v].word}</span>
            <span className={counts[v] ? "text-paper" : "text-slate/40"}>{counts[v]}</span>
          </div>
        ))}
      </div>

      <div className="label mt-4 pt-2 rule-t leading-relaxed">
        {quotes} quotes · {nSources} sources
        <br />
        checked by an independent model
      </div>
    </div>
  );
}
