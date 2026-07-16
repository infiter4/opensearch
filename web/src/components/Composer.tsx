import { useState } from "react";
import { activeExchanges, useChat } from "../state/chat";

const MODES = [
  { id: "lite", note: "one researcher · one search lane · a quick answer" },
  { id: "pro", note: "three researchers · two search lanes · unsupported claims sent back for correction" },
  { id: "deep", note: "four researchers + a red team · academic lane · provenance graph · full audit report" },
];

export function Composer() {
  const ask = useChat((s) => s.ask);
  const stop = useChat((s) => s.stop);
  const running = useChat((s) => activeExchanges(s).find((e) => e.phase !== "done" && e.phase !== "error"));
  const [q, setQ] = useState("");
  const [mode, setMode] = useState("pro");
  const busy = !!running;

  const submit = () => {
    const question = q.trim();
    if (!question || busy) return;
    setQ("");
    void ask(question, mode);
  };

  return (
    <div className="flex items-end gap-4">
      <div className="flex-1">
        <textarea
          rows={1}
          value={q}
          placeholder="Ask a question…"
          className="w-full resize-none bg-transparent outline-none text-[16px] leading-[1.6] py-1"
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
        />
      </div>
      <div className="flex items-center gap-1 shrink-0">
        {MODES.map((m) => (
          <button
            key={m.id}
            data-note={m.note}
            onClick={() => setMode(m.id)}
            className={`font-mono text-[10px] tracking-[0.14em] uppercase px-2 py-1 transition-colors ${
              mode === m.id ? "text-amber border-b border-amber" : "text-slate hover:text-paper border-b border-transparent"
            }`}
          >
            {m.id}
          </button>
        ))}
      </div>
      {busy ? (
        // Three researchers and dozens of checks are in flight; a run you cannot call off is a
        // run that burns rate limit while you wait for an answer you no longer want.
        <button
          onClick={() => running && stop(running.key)}
          data-note="stop this run"
          className="font-mono text-[10px] tracking-[0.16em] uppercase px-3 py-1.5 border border-amber text-amber hover:bg-amber/10 transition-colors shrink-0"
        >
          stop
        </button>
      ) : (
        <button
          onClick={submit}
          disabled={!q.trim()}
          className="font-mono text-[10px] tracking-[0.16em] uppercase px-3 py-1.5 border border-[var(--rule-2)] text-paper disabled:opacity-25 hover:border-amber hover:text-amber transition-colors shrink-0"
        >
          ask ↵
        </button>
      )}
    </div>
  );
}
