import { useMemo } from "react";
import { MARK, worstOf, type LedgerRow, type Verdict } from "../lib/protocol";
import { VerdictShape } from "../lib/shapes";
import { checkKey, useChat, type Exchange } from "../state/chat";

/* Every claim against every source it cited. Sparse on purpose: a blank cell means
   that sentence never cited that source, which is not a defect. The blocks down the diagonal are
   the researchers working independently; a mark outside its block is two researchers landing on the
   same source on their own — corroboration you can point at. */

export function Grid({ ex, showDraft }: { ex: Exchange; showDraft: boolean }) {
  const viewSource = useChat((s) => s.viewSource);
  const focus = useChat((s) => s.focus);
  const focusSentence = useChat((s) => s.focusSentence);
  const checks = showDraft ? ex.draft : ex.checks;

  const rows = useMemo<LedgerRow[]>(
    () => ex.ledger.rows.length
      ? ex.ledger.rows
      : [...new Set(Object.values(checks).map((c) => c.sentence_id))].map((sid, i) => ({
          sentence_id: sid, agent_id: sid.split(".")[0], text: "", order: i,
        })),
    [ex.ledger.rows, checks],
  );
  const cols = useMemo(
    () => (ex.ledger.cols.length ? ex.ledger.cols : Object.values(ex.sources)),
    [ex.ledger.cols, ex.sources],
  );
  if (!rows.length || !cols.length) return null;

  return (
    <div data-testid="matrix">
      <div className="label mb-4 flex flex-wrap items-center gap-x-5 gap-y-2">
        <span>verification matrix — claim × source</span>
        <span className="flex-1" />
        {(["supported", "weak", "unsupported", "contradicted", "retracted"] as Verdict[]).map((v) => (
          <span key={v} className="flex items-center gap-1.5 !text-faint normal-case tracking-normal">
            <span className="text-ink/70"><VerdictShape v={v} size={9} /></span>{MARK[v].word}
          </span>
        ))}
      </div>
      <div className="overflow-x-auto pb-1">
        <table className="border-separate" style={{ borderSpacing: 3 }}>
          <thead>
            <tr>
              <td />
              {cols.map((c) => (
                <td key={c.id} className="align-bottom">
                  <button
                    className="font-mono text-[9px] text-faint hover:text-ink block max-h-24 overflow-hidden transition-colors"
                    style={{ writingMode: "vertical-rl" }}
                    data-note={c.title || c.url}
                    onClick={() => viewSource(ex.key, c.id)}
                  >
                    {c.id} {c.domain?.replace(/^www\./, "").slice(0, 16)}
                  </button>
                </td>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const rowChecks = cols.map((c) => checks[checkKey(r.sentence_id, c.id)]);
              const wv: Verdict = r.retracted && !showDraft
                ? "retracted"
                : worstOf(rowChecks.filter(Boolean).map((c) => c!.verdict));
              const on = focusSentence === r.sentence_id;
              return (
                <tr key={r.sentence_id}>
                  <td
                    className={`pr-4 max-w-[300px] cursor-pointer rounded-[2px] ${on ? "bg-[var(--sel)]" : "hover:bg-raised"}`}
                    onClick={() => focus(on ? null : r.sentence_id)}
                  >
                    <div className="flex items-baseline gap-2.5 px-1">
                      <span className="font-mono text-[9px] text-faint shrink-0">{r.agent_id}</span>
                      <span className={`text-[12.5px] truncate ${wv === "retracted" ? "line-through text-faint" : "text-ink/70"}`}>
                        {r.text}
                      </span>
                    </div>
                  </td>
                  {cols.map((c) => {
                    const ch = checks[checkKey(r.sentence_id, c.id)];
                    if (!ch) {
                      return (
                        <td key={c.id}>
                          <div className="w-[18px] h-[18px] grid place-items-center select-none">
                            <span className="w-[2px] h-[2px] rounded-full bg-faint/60" />
                          </div>
                        </td>
                      );
                    }
                    const v: Verdict = r.retracted && !showDraft ? "retracted" : ch.verdict;
                    return (
                      <td key={c.id}>
                        <button
                          data-testid="matrix-cell"
                          className="w-[18px] h-[18px] grid place-items-center rounded-[2px] text-ink/75 hover:bg-raised hover:text-ink tick transition-colors"
                          data-note={`${MARK[v].word} — ${MARK[v].note}${ch.reason ? `\n\n${ch.reason.slice(0, 150)}` : ""}`}
                          aria-label={MARK[v].word}
                          onClick={() => viewSource(ex.key, c.id, ch.quote)}
                        >
                          <VerdictShape v={v} />
                        </button>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
