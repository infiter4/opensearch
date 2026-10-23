import { useEffect, useRef, useState } from "react";
import { LOG_GLYPH, type LogEntry, type LogKind } from "../lib/protocol";
import { isLive, useChat, type Exchange } from "../state/chat";

/* The run, end to end: planning, searching, reading, drafting, claim extraction, every check
   against its source, every correction and withdrawal, the merge, the tally.
   Read straight from the recorded log — real elapsed times, nothing reconstructed. */

// The red is reserved for trouble, exactly as the marks use it. Everything else is quiet.
const TONE: Record<LogKind, string> = {
  plan: "text-ink/75", search: "text-mute", read: "text-mute",
  draft: "text-ink/75", claims: "text-mute",
  ok: "text-ink/45", weak: "text-ink/60", bad: "text-signal", clash: "text-signal",
  fix: "text-signal", fixed: "text-ink/75", drop: "text-signal",
  merge: "text-ink/75", final: "text-ink", graph: "text-ink/75",
  report: "text-ink/75", warn: "text-signal",
};

const clock = (ms: number) => {
  const s = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

/** What a row expands into, if anything. A row that opens something says so with a ▸. */
function expansion(e: LogEntry, ex: Exchange): { label: string; body: string[] } | null {
  if (e.kind === "claims" && e.who) {
    const cl = ex.claimsBy[e.who] ?? [];
    if (!cl.length) return null;
    return {
      label: `${cl.length} claims from ${e.who}`,
      body: cl.map((c) => `${c.sentence_id}  ${c.text}${c.source_ids?.length ? `  → [${c.source_ids.join("][")}]` : ""}`),
    };
  }
  if (e.kind === "draft" && e.who) {
    const r = ex.researchers[e.who];
    const sents = r?.sentences ?? [];
    if (!r?.text || !sents.length) return null;
    return {
      label: `${sents.length} sentences from ${e.who}`,
      body: sents.map((s) => {
        const txt = r.text.slice(s.start, s.end).trim();
        return `${s.id}  ${txt}${s.cited?.length ? `  → [${s.cited.join("][")}]` : ""}`;
      }).filter((t) => t.split("  ").slice(1).join("  ").trim()),
    };
  }
  return null;
}

function Row({ e, ex }: { e: LogEntry; ex: Exchange }) {
  const [open, setOpen] = useState(false);
  const focus = useChat((s) => s.focus);
  const exp = expansion(e, ex);

  // A verdict row points at a sentence: clicking it highlights that sentence in the answer.
  const sid = /^(\w+\.s\d+)/.exec(e.what)?.[1];
  const clickable = !!exp || !!sid;

  return (
    <>
      <div
        data-testid="log-row"
        className={`tick flex gap-2.5 items-baseline px-1 -mx-1 rounded-[2px] ${clickable ? "cursor-pointer hover:bg-raised" : ""}`}
        onClick={() => { if (exp) setOpen((v) => !v); else if (sid) focus(sid); }}
      >
        <span className="text-faint shrink-0 tabular-nums">{clock(e.t)}</span>
        <span className={`${TONE[e.kind] ?? ""} shrink-0 w-3 text-center`}>{LOG_GLYPH[e.kind]}</span>
        <span className="text-faint shrink-0 w-6 truncate">{e.who ?? ""}</span>
        {/* min-w-0 is what actually lets truncate work inside a flex row — without it the row
            grows to fit a long 429 body and overlaps whatever sits beside it. */}
        <span className={`${TONE[e.kind]} truncate min-w-0`} title={`${e.what}${e.detail ? ` · ${e.detail}` : ""}`}>
          {exp && <span className="text-faint">{open ? "▾ " : "▸ "}</span>}
          {e.what}
          {e.detail && <span className="text-faint"> · {e.detail}</span>}
        </span>
      </div>

      {open && exp && (
        <div className="ml-[3.6rem] my-1.5 border-l border-line-2 pl-3 py-1 space-y-0.5 fade">
          <div className="label !text-[9px] mb-1">{exp.label}</div>
          {exp.body.map((line, i) => (
            <div key={i} className="text-[10.5px] text-ink/60 leading-relaxed break-words">{line}</div>
          ))}
        </div>
      )}
    </>
  );
}

export function Activity({ ex, full = false }: { ex: Exchange; full?: boolean }) {
  const running = isLive(ex.phase);
  const boxRef = useRef<HTMLDivElement>(null);
  const log = ex.log ?? [];   // threads saved before the log existed
  const rows = full ? log : log.slice(-60);

  // Follow the tail while it runs; leave it alone once it stops so a reader can scroll back.
  useEffect(() => {
    if (running && boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [log.length, running]);

  const status =
    ex.phase === "researching" ? "searching and reading sources"
    : ex.phase === "checking" ? "checking every claim against its source"
    : ex.phase === "repairing" ? "correcting the claims that failed"
    : ex.phase === "writing" ? "writing the verified answer"
    : "";

  return (
    <div data-testid="activity" className="font-mono text-[11px] leading-[1.9] min-w-0">
      <div className="label pb-2 mb-2 rule-b flex items-center gap-2">
        {running && <span className="w-[6px] h-[6px] rounded-full bg-signal live-dot" />}
        activity
        <span className="flex-1" />
        <span className="text-faint tabular-nums">{log.length}</span>
      </div>

      <div
        ref={boxRef}
        className={`${full ? "max-h-[440px]" : "max-h-[280px]"} overflow-y-auto pr-2`}
        style={running ? { maskImage: "linear-gradient(to bottom, transparent, black 28px)" } : undefined}
      >
        {rows.map((e, i) => <Row key={i} e={e} ex={ex} />)}
        {!rows.length && <div className="text-faint italic font-serif text-[14px]">starting…</div>}
      </div>

      {running && status && (
        <div className="label !text-faint mt-2 pt-2 rule-t">
          {status}
          {Object.keys(ex.sources).length > 0 && ` · ${Object.keys(ex.sources).length} sources read`}
        </div>
      )}
    </div>
  );
}
