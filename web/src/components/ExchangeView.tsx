import { useMemo, useState } from "react";
import { MARK, worstOf, type SentenceRef, type Verdict } from "../lib/protocol";
import { Prose, type SentenceDress } from "../lib/prose";
import { useChat, type Exchange } from "../state/chat";
import { Desk } from "./Desk";
import { Flowchart } from "./Flowchart";
import { Graph3D } from "./Graph3D";
import { Grid } from "./Grid";
import { Wire } from "./Wire";

const WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
  "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
  "eighteen", "nineteen", "twenty"];
const spell = (n: number) => (n <= 20 ? WORDS[n] : String(n));

export function ExchangeView({ ex, index }: { ex: Exchange; index: number }) {
  const { showDraft, toggleDraft, viewSource, focus, focusSentence } = useChat();
  const [gridOpen, setGridOpen] = useState(false);
  const [graphOpen, setGraphOpen] = useState(false);
  const [flowOpen, setFlowOpen] = useState(false);
  const draft = !!showDraft[ex.key];
  const running = ex.phase !== "done" && ex.phase !== "error";
  const checks = draft ? ex.draft : ex.checks;

  const bySentence = useMemo(() => {
    const grouped = new Map<string, { v: Verdict; reason: string }[]>();
    for (const c of Object.values(checks)) {
      if (!grouped.has(c.sentence_id)) grouped.set(c.sentence_id, []);
      grouped.get(c.sentence_id)!.push({ v: c.verdict, reason: c.reason });
    }
    const m = new Map<string, { verdict: Verdict; note: string }>();
    for (const [sid, list] of grouped) {
      const wv = worstOf(list.map((x) => x.v));
      const why = list.find((x) => x.v === wv)?.reason ?? "";
      m.set(sid, { verdict: wv, note: `${MARK[wv].word.toUpperCase()} — ${why || MARK[wv].note}` });
    }
    return m;
  }, [checks]);

  const retractedById = useMemo(
    () => new Map(ex.retracted.map((r) => [r.sentence_id, r])),
    [ex.retracted],
  );

  const dress = (s: SentenceRef): SentenceDress => {
    const hit = bySentence.get(s.id);
    const ret = retractedById.get(s.id) ?? ex.ledger.rows.find((r) => r.sentence_id === s.id && r.retracted);
    const zeroWidth = s.start === s.end;
    return {
      verdict: hit?.verdict ?? null,
      repairing: ex.repairing.has(s.id),
      healed: !draft && ex.healed.has(s.id),
      focused: focusSentence === s.id,
      retractedText: zeroWidth && ret ? ret.text : undefined,
      note: hit?.note ?? (ret ? `WITHDRAWN — ${ret.reason ?? ""}` : undefined),
    };
  };

  const onCite = (sourceId: number, sentenceId: string) =>
    viewSource(ex.key, sourceId, checks[`${sentenceId}:${sourceId}`]?.quote);

  const t = ex.trust;
  const nSources = Object.keys(ex.sources).length;

  return (
    <article className="pt-8 pb-10 rule-b last:border-b-0">
      {/* case header */}
      <div className="label flex flex-wrap items-center gap-x-3 gap-y-1">
        <span>case №&nbsp;{String(index + 1).padStart(2, "0")}</span>
        <span className="text-slate/40">·</span>
        <span>{ex.mode}</span>
        {nSources > 0 && <><span className="text-slate/40">·</span><span>{spell(nSources)} sources</span></>}
        {!running && ex.elapsed > 0 && <><span className="text-slate/40">·</span><span>{Math.round(ex.elapsed)}s</span></>}
        {ex.cacheMode === "replay" && <><span className="text-slate/40">·</span><span className="text-amber">replay</span></>}
        <span className="flex-1" />
        {!running && t && (
          <button
            className={`font-mono text-[10px] tracking-[0.16em] uppercase border px-2.5 py-1 transition-colors ${
              draft ? "border-amber text-amber" : "border-[var(--rule-2)] text-slate hover:text-paper"
            }`}
            data-note="rewind to the copy before the desk touched it"
            onClick={() => toggleDraft(ex.key)}
          >
            {draft ? "first draft" : "as shipped"}
          </button>
        )}
      </div>

      <h2 className="text-[26px] leading-[1.28] mt-3 max-w-[42ch]">{ex.question}</h2>

      {!running && t && (
        <div className="label mt-2 !text-[10.5px]">
          {draft ? (
            <span className="text-amber">
              before the desk — {spell(t.unsupported + t.contradicted + t.retracted)} of these sentences did not hold
            </span>
          ) : (
            <>passed the desk — {spell(t.supported)} of {spell(t.total)} sentences held</>
          )}
        </div>
      )}

      {/* live: the wire */}
      {running && (
        <div className="mt-5 grid gap-6" style={{ gridTemplateColumns: "minmax(0,1fr) 260px" }}>
          <Wire ex={ex} />
          {Object.keys(ex.checks).length > 0 && (
            <div className="label">
              {Object.keys(ex.checks).length} claims cross-examined
            </div>
          )}
        </div>
      )}

      {/* the galley + the desk */}
      {(ex.answer.text || !running) && (
        <div className="mt-6 grid gap-10" style={{ gridTemplateColumns: "minmax(0,1fr) 210px" }}>
          <div className={`text-[16.5px] leading-[1.75] max-w-[64ch] ${running ? "setting" : ""}`}>
            <Prose
              text={ex.answer.text}
              sentences={ex.answer.sentences}
              dress={dress}
              onCite={onCite}
              onFocus={(sid) => focus(focusSentence === sid ? null : sid)}
            />
          </div>
          <div className="pt-1">{!running && <Desk ex={ex} />}</div>
        </div>
      )}

      {/* footer controls */}
      {!running && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 mt-7">
          <button className={`label hover:!text-paper ${gridOpen ? "!text-paper" : ""}`}
                  onClick={() => setGridOpen(!gridOpen)}>
            {gridOpen ? "▾" : "▸"} the grid
          </button>
          {ex.graph && (
            <>
              <button className={`label hover:!text-paper ${graphOpen ? "!text-paper" : ""}`}
                      onClick={() => setGraphOpen(!graphOpen)}>
                {graphOpen ? "▾" : "▸"} provenance
              </button>
              <button className={`label hover:!text-paper ${flowOpen ? "!text-paper" : ""}`}
                      onClick={() => setFlowOpen(!flowOpen)}>
                {flowOpen ? "▾" : "▸"} how it was made
              </button>
            </>
          )}
          {ex.artifacts.map((a) => (
            <a key={a.id} className="label hover:!text-paper !text-amber"
               href={`${a.url}?query_id=${ex.queryId}`} target="_blank" rel="noreferrer"
               data-note="compiled by the reporter from the verdict matrix">
              the report ↗
            </a>
          ))}
        </div>
      )}

      {gridOpen && !running && <div className="mt-4"><Grid ex={ex} showDraft={draft} /></div>}
      {graphOpen && ex.graph && <div className="mt-4 rule-t pt-3"><Graph3D ex={ex} /></div>}
      {flowOpen && <div className="mt-4 rule-t pt-3"><Flowchart ex={ex} /></div>}

      {ex.notes.length > 0 && (
        <div className="mt-5 space-y-1">
          {ex.notes.map((n, i) => (
            <div key={i} className="font-mono text-[10.5px] text-amber/80">
              caught · {n.scope}: {n.message}
            </div>
          ))}
        </div>
      )}
    </article>
  );
}
