import { useMemo } from "react";
import { MARK, worstOf, type LedgerRow, type Verdict } from "../lib/protocol";
import { checkKey, useChat, type Exchange } from "../state/chat";

/* THE GRID — every claim against every source it cited. Sparse on purpose: a blank cell means
   that sentence never cited that source, which is not a defect. The blocks down the diagonal are
   the angles working independently; a mark outside its block is two researchers landing on the
   same source on their own — corroboration you can point at. */

function tone(v: Verdict): string {
  return v === "contradicted" || v === "retracted" ? "text-amber" : "text-paper/70";
}

export function Grid({ ex, showDraft }: { ex: Exchange; showDraft: boolean }) {
  const { viewSource, focus, focusSentence } = useChat();
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
    <div>
      <div className="label rule-b pb-1.5 mb-2">the grid — claim × source</div>
      <div className="overflow-x-auto">
        <table className="border-separate" style={{ borderSpacing: 2 }}>
          <thead>
            <tr>
              <td />
              {cols.map((c) => (
                <td key={c.id} className="align-bottom">
                  <button
                    className="label !text-[9px] hover:!text-paper block max-h-20 overflow-hidden"
                    style={{ writingMode: "vertical-rl" }}
                    data-note={c.title || c.url}
                    onClick={() => viewSource(ex.key, c.id)}
                  >
                    {c.id} {c.domain?.replace(/^www\./, "").slice(0, 14)}
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
                    className={`pr-3 max-w-[290px] cursor-pointer ${on ? "bg-[var(--sel)]" : ""}`}
                    onClick={() => focus(on ? null : r.sentence_id)}
                  >
                    <div className="flex items-baseline gap-2">
                      <span className="font-mono text-[9px] text-slate/70 shrink-0">{r.agent_id}</span>
                      <span
                        className={`font-mono text-[10px] truncate ${
                          wv === "retracted" ? "line-through text-slate/60" : "text-paper/60"
                        }`}
                      >
                        {r.text}
                      </span>
                    </div>
                  </td>
                  {cols.map((c) => {
                    const ch = checks[checkKey(r.sentence_id, c.id)];
                    if (!ch) {
                      return (
                        <td key={c.id}>
                          <div className="w-4 text-center text-slate/20 select-none font-mono text-[10px]">·</div>
                        </td>
                      );
                    }
                    const v: Verdict = r.retracted && !showDraft ? "retracted" : ch.verdict;
                    return (
                      <td key={c.id}>
                        <button
                          className={`cellbox cell-in ${tone(v)}`}
                          data-note={`${MARK[v].word} — ${MARK[v].note}${ch.reason ? `\n\n${ch.reason.slice(0, 150)}` : ""}`}
                          onClick={() => viewSource(ex.key, c.id, ch.quote)}
                        >
                          {MARK[v].glyph}
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
