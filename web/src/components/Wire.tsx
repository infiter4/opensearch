import { useMemo } from "react";
import type { Exchange } from "../state/chat";

/* THE WIRE — how it was made, as it happens. A timestamped ticker of every real action the
   researchers took: angles opened, pages read, quotes pinned, sentences sent to the desk.
   It is the receipt for the research itself, not a spinner pretending to be one. */

interface Tick { t: number; who: string; what: string; quote?: boolean }

function build(ex: Exchange): Tick[] {
  const out: Tick[] = [];
  const t0 = ex.startedAt;
  const at = (ms?: number) => Math.max(0, Math.round(((ms ?? Date.now()) - t0) / 1000));

  if (ex.order.length) out.push({ t: 0, who: "", what: `split into ${ex.order.length} angles` });

  for (const id of ex.order) {
    const r = ex.researchers[id];
    if (!r) continue;
    for (const tool of r.tools) {
      let arg = tool.args ?? "";
      try {
        const o = JSON.parse(arg);
        arg = o.query ?? o.url ?? arg;
      } catch { /* bare string */ }
      arg = arg.replace(/^https?:\/\/(www\.)?/, "");
      const verb = tool.tool === "web_search" ? "searched" : "read";
      out.push({ t: at(), who: id, what: `${verb} ${arg.slice(0, 44)}` });
    }
  }

  // A pinned quote is a verified span the desk located in the real page by string search.
  for (const c of Object.values(ex.checks)) {
    if (c.verdict === "supported" && c.quote) {
      out.push({ t: at(), who: c.sentence_id.split(".")[0], what: `pinned “${c.quote.slice(0, 52)}…”`, quote: true });
    }
  }
  return out;
}

const clock = (s: number) => `:${String(s % 60).padStart(2, "0")}`;

export function Wire({ ex }: { ex: Exchange }) {
  const ticks = useMemo(() => build(ex), [ex]);
  const running = ex.phase !== "done" && ex.phase !== "error";

  const status =
    ex.phase === "researching" ? "working the angles"
    : ex.phase === "checking" ? "at the desk — cross-examining every claim"
    : ex.phase === "repairing" ? "the desk sent copy back for correction"
    : ex.phase === "writing" ? "setting the verified copy"
    : "";

  return (
    <div className="font-mono text-[11px] leading-[1.9]">
      <div className="label rule-b pb-1.5 mb-2 flex items-center gap-2">
        {running && <span className="live-dot text-amber">●</span>}
        the wire · how it was made
      </div>

      <div className="max-h-[220px] overflow-y-auto pr-2">
        {ticks.slice(-40).map((k, i) => (
          <div key={i} className="tick flex gap-2">
            <span className="text-slate/60 shrink-0">{clock(k.t)}</span>
            {k.who && <span className="text-slate shrink-0">{k.who}</span>}
            <span className={k.quote ? "text-amber truncate" : "text-paper/70 truncate"}>{k.what}</span>
          </div>
        ))}
        {!ticks.length && <div className="text-slate">opening the case…</div>}
      </div>

      {running && status && (
        <div className="label mt-2 pt-1.5 rule-t">
          {status}
          {Object.keys(ex.sources).length > 0 && ` · ${Object.keys(ex.sources).length} sources read`}
        </div>
      )}
    </div>
  );
}
