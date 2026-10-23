import { useMemo, useState, type ReactNode } from "react";
import { MARK, tallyOf, worstOf, type SentenceRef, type Verdict } from "../lib/protocol";
import { Prose, type SentenceDress } from "../lib/prose";
import { isLive, useChat, type Exchange } from "../state/chat";
import { Activity } from "./Activity";
import { Flowchart } from "./Flowchart";
import { Graph3D } from "./Graph3D";
import { Grid } from "./Grid";
import { ModelViewer } from "./ModelViewer";
import { Progress } from "./Progress";
import { Summary } from "./Summary";

export function ExchangeView({ ex }: { ex: Exchange; index: number }) {
  // Narrow selectors: a run streams ~10 events a second, and subscribing to the whole store
  // re-rendered EVERY exchange on the page — every answer's prose — on each one of them.
  const draft = useChat((s) => !!s.showDraft[ex.key]);
  const focusSentence = useChat((s) => s.focusSentence);
  const toggleDraft = useChat((s) => s.toggleDraft);
  const viewSource = useChat((s) => s.viewSource);
  const focus = useChat((s) => s.focus);
  const retry = useChat((s) => s.retry);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [modelOpen, setModelOpen] = useState<string | null>(null);
  const flip = (k: string) => setOpen((o) => ({ ...o, [k]: !o[k] }));

  const running = isLive(ex.phase);
  const isTask = ex.kind === "task";   // routed to the doer: no research, no fact-checking chrome
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

  const meta: ReactNode[] = [
    <span key="m" className={isTask ? "text-signal" : ""}>{isTask ? "task" : (ex.resolvedMode || ex.mode)}</span>,
  ];
  if (ex.workspace) meta.push(<span key="w" className="text-signal" data-note="researched your ingested documents, not the web">corpus: {ex.workspace}</span>);
  if (isTask && ex.routeTitle) meta.push(<span key="r">{ex.routeTitle}</span>);
  if (nSources > 0) meta.push(<span key="s">{nSources} {ex.workspace ? "passages" : "sources"}</span>);
  if (!running && ex.elapsed > 0) meta.push(<span key="e">{Math.round(ex.elapsed)}s</span>);
  if (ex.cacheMode === "replay") meta.push(<span key="c" className="text-signal">replay</span>);

  return (
    <article
      data-testid="exchange"
      data-phase={ex.phase}
      data-kind={ex.kind ?? "research"}
      className="pt-12 pb-14 border-b border-line last:border-b-0 rise"
    >
      <div className="label flex flex-wrap items-center gap-x-2.5 gap-y-1">
        {meta.map((m, i) => (
          <span key={i} className="flex items-center gap-2.5">
            {i > 0 && <span className="w-[3px] h-[3px] rounded-full bg-faint" />}
            {m}
          </span>
        ))}
        <span className="flex-1" />
        {!running && t && (
          <button
            data-testid="draft-toggle"
            onClick={() => toggleDraft(ex.key)}
            data-note="show the first draft, before any corrections"
            aria-pressed={draft}
            className="flex items-center p-[3px] rounded-full border border-line-2 font-mono text-[9.5px] tracking-[0.14em] uppercase"
          >
            <span className={`px-2.5 py-1 rounded-full transition-colors ${!draft ? "bg-ink text-ground" : "text-faint"}`}>final</span>
            <span className={`px-2.5 py-1 rounded-full transition-colors ${draft ? "bg-signal text-ground" : "text-faint"}`}>first draft</span>
          </button>
        )}
      </div>

      <h2 className="display font-[350] text-[28px] sm:text-[36px] leading-[1.12] tracking-[-0.018em] mt-4 max-w-[28ch] text-balance">
        {ex.question}
      </h2>

      {/* At rest but unfinished: say which, and offer the one useful action in place. */}
      {(ex.phase === "interrupted" || ex.phase === "error") && (
        <div className="mt-5 flex items-center gap-4 flex-wrap">
          <span className="flex items-center gap-2 label !text-signal">
            <span className="w-1.5 h-1.5 rounded-full bg-signal" /> {ex.phase === "error" ? "failed" : "interrupted"}
          </span>
          <span className="text-[14px] italic text-mute">
            {ex.phase === "error" ? "the run could not finish — the reason is below" : "the run stopped before it finished"}
          </span>
          <button
            data-testid="resume"
            className="label !text-ink border border-line-2 rounded-full px-3 py-1.5 hover:border-ink transition-colors"
            data-note="run it again — most of the work is already cached"
            onClick={() => void retry(ex.key)}
          >
            {ex.phase === "error" ? "try again ↻" : "resume ↻"}
          </button>
        </div>
      )}

      {!running && t && (
        <div data-testid="tally" className="mt-3 text-[15px] italic text-mute">
          {draft ? (
            <span className="text-signal">
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
        <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_220px]">
          <Activity ex={ex} />
          {!isTask && <Progress ex={ex} />}
        </div>
      )}

      {(ex.answer.text || !running) && (
        <div className="mt-8 grid gap-10 lg:gap-14 lg:grid-cols-[minmax(0,1fr)_220px]">
          <div className={`text-[17.5px] sm:text-[18.5px] leading-[1.72] max-w-[66ch] min-w-0 ${running ? "setting" : ""}`}>
            <Prose
              text={ex.answer.text}
              sentences={ex.answer.sentences}
              dress={dress}
              onCite={onCite}
              onFocus={(sid) => focus(focusSentence === sid ? null : sid)}
            />
          </div>
          <div>{!running && !isTask && <Summary ex={ex} draft={draft} />}</div>
        </div>
      )}

      {/* Sources that disagree with each other. Averaging them away is the failure this product
          exists to prevent, so the conflict is stated rather than quietly resolved. */}
      {!running && ex.conflicts.length > 0 && (
        <div data-testid="conflicts" className="mt-10 max-w-[66ch]">
          <div className="label mb-3">sources disagree</div>
          {ex.conflicts.map((c, i) => (
            <div key={i} className="text-[15px] text-ink/80 leading-relaxed mb-2 flex gap-3 items-baseline">
              <svg width="9" height="9" viewBox="0 0 10 10" className="shrink-0 translate-y-[1px]" aria-hidden>
                <path d="M5 0.6 9.4 5 5 9.4 0.6 5Z" fill="var(--signal)" />
              </svg>
              <span>{c.reason ?? "two cited sources make opposite claims"}</span>
            </div>
          ))}
        </div>
      )}

      {!running && (
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3 mt-10">
          {/* A task run is not fact-checked: it has no claims, so no matrix to open. */}
          {!isTask && (
            <Toggle testid="toggle-matrix" open={!!open.matrix} onClick={() => flip("matrix")}
                    note="every claim against every source it cited">
              verification matrix
            </Toggle>
          )}
          <Toggle testid="toggle-log" open={!!open.log} onClick={() => flip("log")}
                  note="every step this run took, with timings">
            activity log <span className="text-faint">{ex.log?.length ?? 0}</span>
          </Toggle>
          {/* Research-only views: a task run has no researchers, sources, or checks to draw. */}
          {!isTask && <>
            <Toggle testid="toggle-flow" open={!!open.flow} onClick={() => flip("flow")}
                    note="the answer as a flowchart: what it names and how those things relate">
              flowchart
            </Toggle>
            <Toggle testid="toggle-graph" open={!!open.graph} onClick={() => flip("graph")}
                    note="the answer as a 3D knowledge graph — things it names and how they relate">
              knowledge graph
            </Toggle>
          </>}
          {ex.artifacts.map((a) => (
            a.kind === "model" ? (
              <Toggle key={a.id} testid="artifact-model" open={modelOpen === a.id} accent
                      onClick={() => setModelOpen(modelOpen === a.id ? null : a.id)}
                      note="an interactive 3D model — drag to orbit, scroll to zoom">
                3D model: {a.name}
              </Toggle>
            ) : (
              <a key={a.id} data-testid="artifact"
                 className="label !text-signal hover:!no-underline flex items-center gap-2 group"
                 href={`${a.url}?query_id=${ex.queryId}`} target="_blank" rel="noreferrer"
                 data-note={isTask ? "the file the task produced — opens in the browser" : "compiled by the reporting agent from the verification matrix"}>
                <span className="w-[13px] h-[13px] rounded-full border border-signal grid place-items-center group-hover:bg-signal group-hover:text-ground transition-colors text-[8px] leading-none">↗</span>
                {isTask ? a.name : "audit report"}
              </a>
            )
          ))}
        </div>
      )}

      {open.log && !running && <Panel><Activity ex={ex} full /></Panel>}
      {open.matrix && !running && <Panel><Grid ex={ex} showDraft={draft} /></Panel>}
      {open.graph && <Panel><Graph3D ex={ex} /></Panel>}
      {open.flow && <Panel><Flowchart ex={ex} /></Panel>}
      {modelOpen && (() => {
        const a = ex.artifacts.find((x) => x.id === modelOpen);
        return a ? <Panel><ModelViewer url={`${a.url}?query_id=${ex.queryId}`} /></Panel> : null;
      })()}

      {ex.notes.length > 0 && (
        <div data-testid="notes" className="mt-6 space-y-1">
          {ex.notes.map((n, i) => (
            <div key={i} className="font-mono text-[11px] text-signal/85 break-words">
              {n.scope}: {n.message}
            </div>
          ))}
        </div>
      )}
    </article>
  );
}

function Panel({ children }: { children: ReactNode }) {
  return <div className="mt-6 pt-5 rule-t fade">{children}</div>;
}

/** A disclosure: a hairline plus that turns into a cross when open. */
function Toggle({ open, onClick, children, testid, note, accent }: {
  open: boolean; onClick: () => void; children: ReactNode; testid: string; note?: string; accent?: boolean;
}) {
  return (
    <button
      data-testid={testid}
      data-note={note}
      aria-expanded={open}
      onClick={onClick}
      className={`group flex items-center gap-2 label transition-colors ${
        accent ? "!text-signal" : open ? "!text-ink" : "hover:!text-ink"
      }`}
    >
      <svg width="9" height="9" viewBox="0 0 9 9" aria-hidden
           className={`transition-transform duration-300 ${open ? "rotate-45" : ""}`}>
        <path d="M4.5 0.5v8M0.5 4.5h8" stroke="currentColor" strokeWidth="1.1" />
      </svg>
      {children}
    </button>
  );
}
