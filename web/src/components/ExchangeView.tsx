import { useMemo, useState } from "react";
import { MARK, tallyOf, worstOf, type SentenceRef, type Verdict } from "../lib/protocol";
import { Prose, type SentenceDress } from "../lib/prose";
import { useChat, type Exchange } from "../state/chat";
import { Activity } from "./Activity";
import { Flowchart } from "./Flowchart";
import { Graph3D } from "./Graph3D";
import { Grid } from "./Grid";
import { Progress } from "./Progress";
import { Summary } from "./Summary";

export function ExchangeView({ ex, index }: { ex: Exchange; index: number }) {
  const { showDraft, toggleDraft, viewSource, focus, focusSentence, retry } = useChat();
  const [gridOpen, setGridOpen] = useState(false);
  const [graphOpen, setGraphOpen] = useState(false);
  const [flowOpen, setFlowOpen] = useState(false);
  const [logOpen, setLogOpen] = useState(false);
  const draft = !!showDraft[ex.key];
  const running = ex.phase !== "done" && ex.phase !== "error" && ex.phase !== "interrupted";
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
      struck: !draft,   // at iteration 0 it had not been withdrawn yet
      note: hit?.note ?? (ret ? `WITHDRAWN — ${ret.reason ?? ""}` : undefined),
    };
  };

  const onCite = (sourceId: number, sentenceId: string) =>
    viewSource(ex.key, sourceId, checks[`${sentenceId}:${sourceId}`]?.quote);

  const t = ex.trust;
  const draftT = useMemo(() => tallyOf(Object.values(ex.draft)), [ex.draft]);
  const nSources = Object.keys(ex.sources).length;
  const fixed = ex.healed.size;

  return (
    <article className="pt-8 pb-10 rule-b last:border-b-0">
      <div className="label flex flex-wrap items-center gap-x-3 gap-y-1">
        <span>{ex.mode}</span>
        {nSources > 0 && <><span className="text-slate/40">·</span><span>{nSources} sources</span></>}
        {!running && ex.elapsed > 0 && <><span className="text-slate/40">·</span><span>{Math.round(ex.elapsed)}s</span></>}
        {ex.cacheMode === "replay" && <><span className="text-slate/40">·</span><span className="text-amber">replay</span></>}
        <span className="flex-1" />
        {!running && t && (
          <button
            className={`font-mono text-[10px] tracking-[0.16em] uppercase border px-2.5 py-1 transition-colors ${
              draft ? "border-amber text-amber" : "border-[var(--rule-2)] text-slate hover:text-paper"
            }`}
            data-note="show the first draft, before any corrections"
            onClick={() => toggleDraft(ex.key)}
          >
            {draft ? "first draft" : "final"}
          </button>
        )}
      </div>

      <h2 className="text-[26px] leading-[1.28] mt-3 max-w-[42ch]">{ex.question}</h2>

      {/* A run cannot be re-attached after a reload — the stream endpoint starts runs, it does not
          resume them. Say so plainly and offer the one useful action instead of a dead spinner. */}
      {ex.phase === "interrupted" && (
        <div className="mt-3 flex items-center gap-3 flex-wrap">
          <span className="label !text-amber">interrupted by a page reload</span>
          <button
            className="font-mono text-[10px] tracking-[0.16em] uppercase border border-amber text-amber px-2.5 py-1 hover:bg-amber/10 transition-colors"
            data-note="run it again — most of the work is already cached"
            onClick={() => void retry(ex.key)}
          >
            resume ↻
          </button>
        </div>
      )}

      {!running && t && (
        <div className="label mt-2 !text-[10.5px]">
          {draft ? (
            <span className="text-amber">
              first draft — {draftT.unsupported + draftT.contradicted} of {draftT.total} sentences
              were not supported by the page they cited
            </span>
          ) : (
            <>
              {t.supported} of {t.total} sentences verified
              {fixed > 0 && ` · ${fixed} corrected`}
              {t.retracted > 0 && ` · ${t.retracted} withdrawn`}
            </>
          )}
        </div>
      )}

      {running && (
        <div className="mt-5 grid gap-6" style={{ gridTemplateColumns: "minmax(0,1fr) 210px" }}>
          <Activity ex={ex} />
          <div className="pt-1"><Progress ex={ex} /></div>
        </div>
      )}

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
          <div className="pt-1">{!running && <Summary ex={ex} draft={draft} />}</div>
        </div>
      )}

      {/* Sources that disagree with each other. Averaging them away is the failure this product
          exists to prevent, so the conflict is stated rather than quietly resolved. */}
      {!running && ex.conflicts.length > 0 && (
        <div className="mt-6 rule-t pt-3">
          <div className="label mb-2">sources disagree</div>
          {ex.conflicts.map((c, i) => (
            <div key={i} className="text-[13.5px] text-paper/75 leading-relaxed mb-1.5 flex gap-2">
              <span className="text-amber shrink-0">✕</span>
              <span>{c.reason ?? "two cited sources make opposite claims"}</span>
            </div>
          ))}
        </div>
      )}

      {!running && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 mt-7">
          <button className={`label hover:!text-paper ${gridOpen ? "!text-paper" : ""}`}
                  onClick={() => setGridOpen(!gridOpen)}>
            {gridOpen ? "▾" : "▸"} verification matrix
          </button>
          <button className={`label hover:!text-paper ${logOpen ? "!text-paper" : ""}`}
                  onClick={() => setLogOpen(!logOpen)}
                  data-note="every step this run took, with timings">
            {logOpen ? "▾" : "▸"} activity log ({ex.log?.length ?? 0})
          </button>
          {/* The flowchart is drawn from data this exchange already holds, so it is available for
              every conversation in every mode — it never needed the backend's graph. */}
          <button className={`label hover:!text-paper ${flowOpen ? "!text-paper" : ""}`}
                  onClick={() => setFlowOpen(!flowOpen)}
                  data-note="the run as a flowchart: question → researchers → sources → checks → answer">
            {flowOpen ? "▾" : "▸"} flowchart
          </button>
          {/* Both views read the ANSWER's own entities and relations, fetched on demand — so they
              work in every mode and never needed the run's provenance graph. */}
          <button
            className={`label hover:!text-paper ${graphOpen ? "!text-paper" : ""}`}
            onClick={() => setGraphOpen(!graphOpen)}
            data-note="the answer as a 3D knowledge graph — things it names and how they relate"
          >
            {graphOpen ? "▾" : "▸"} knowledge graph
          </button>
          {ex.artifacts.map((a) => (
            <a key={a.id} className="label hover:!text-paper !text-amber"
               href={`${a.url}?query_id=${ex.queryId}`} target="_blank" rel="noreferrer"
               data-note="compiled by the reporting agent from the verification matrix">
              audit report ↗
            </a>
          ))}
        </div>
      )}

      {logOpen && !running && <div className="mt-4 rule-t pt-3"><Activity ex={ex} full /></div>}
      {gridOpen && !running && <div className="mt-4"><Grid ex={ex} showDraft={draft} /></div>}
      {graphOpen && <div className="mt-4 rule-t pt-3"><Graph3D ex={ex} /></div>}
      {flowOpen && <div className="mt-4 rule-t pt-3"><Flowchart ex={ex} /></div>}

      {ex.notes.length > 0 && (
        <div className="mt-5 space-y-1">
          {ex.notes.map((n, i) => (
            <div key={i} className="font-mono text-[10.5px] text-amber/80">
              {n.scope}: {n.message}
            </div>
          ))}
        </div>
      )}
    </article>
  );
}
