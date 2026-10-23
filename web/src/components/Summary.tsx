import { MARK, tallyOf, type Verdict } from "../lib/protocol";
import { Sigil, VerdictShape } from "../lib/shapes";
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
    <div data-testid="summary" className="lg:sticky lg:top-24">
      <div className="label pb-2 mb-5 rule-b">{draft ? "before verification" : "verification"}</div>

      <div className="grid grid-cols-[auto_minmax(0,1fr)] lg:grid-cols-1 gap-x-7 gap-y-5 items-center">
        <div className="relative w-[128px] h-[128px]">
          <Sigil t={t} size={128} />
          <div className="absolute inset-0 grid place-items-center pointer-events-none">
            <div className="flex items-baseline">
              <span className={`display text-[40px] leading-none font-[380] ${draft ? "text-signal" : ""}`}>{t.supported}</span>
              <span className="display text-[17px] text-mute ml-0.5">/{t.total}</span>
            </div>
          </div>
        </div>

        <div>
          <div className="text-[14px] italic text-mute leading-snug lg:-mt-1">
            sentences verified against their sources
          </div>
          <div className="mt-4 space-y-[7px]">
            {ORDER.map((v) => (
              <div key={v} className="flex items-center gap-2.5 font-mono text-[11px]" data-note={MARK[v].note}>
                <span className={counts[v] ? "text-ink/80" : "text-faint"}><VerdictShape v={v} /></span>
                <span className={`flex-1 ${counts[v] ? "text-ink/75" : "text-faint"}`}>{MARK[v].word}</span>
                <span className={`tabular-nums ${counts[v] ? "text-ink" : "text-faint"}`}>{counts[v]}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="label !text-faint mt-6 pt-3 rule-t leading-relaxed">
        {quotes} quotes · {nSources} sources
        <br />
        checked by an independent model
      </div>
    </div>
  );
}
