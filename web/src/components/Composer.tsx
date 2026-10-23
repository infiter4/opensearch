import { useLayoutEffect, useRef, useState } from "react";
import { activeExchanges, isLive, useChat } from "../state/chat";
import { Workspaces } from "./Workspaces";

const MODES = [
  { id: "auto", note: "let the router pick the depth from the question" },
  { id: "lite", note: "one researcher · one search lane · a quick answer" },
  { id: "pro", note: "three researchers · two search lanes · unsupported claims sent back for correction" },
  { id: "deep", note: "four researchers + a red team · academic lane · provenance graph · full audit report" },
];

export function Composer() {
  const ask = useChat((s) => s.ask);
  const stop = useChat((s) => s.stop);
  // Only a run that is actually moving holds the composer. An interrupted one is at rest: it offers
  // resume in place, and must never leave a stop button that stops nothing.
  const running = useChat((s) => activeExchanges(s).find((e) => isLive(e.phase)));
  const activeWorkspace = useChat((s) => s.activeWorkspace);
  const workspaces = useChat((s) => s.workspaces);
  const [q, setQ] = useState("");
  const [mode, setMode] = useState("auto");
  const box = useRef<HTMLTextAreaElement>(null);
  const busy = !!running;

  // Grow with the question, up to a few lines, then scroll.
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 168)}px`;
  }, [q]);

  const submit = () => {
    const question = q.trim();
    if (!question || busy) return;
    setQ("");
    void ask(question, mode);
  };

  const active = workspaces.find((w) => w.slug === activeWorkspace);

  return (
    <div className="flex flex-col gap-3">
      <Workspaces />

      <div className="flex flex-wrap items-end gap-x-5 gap-y-2">
        <textarea
          ref={box}
          rows={1}
          data-testid="composer-input"
          value={q}
          placeholder={active ? `Ask about “${active.title}”…` : "Ask a question…"}
          className="basis-full sm:basis-0 flex-1 min-w-0 resize-none bg-transparent outline-none text-[18px] leading-[1.55] py-1.5
                     placeholder:italic placeholder:text-faint"
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
        />

        <div role="radiogroup" aria-label="depth" className="flex items-center -ml-2 sm:ml-0 pb-1.5">
          {MODES.map((m) => {
            const on = mode === m.id;
            return (
              <button
                key={m.id}
                role="radio"
                aria-checked={on}
                data-testid={`mode-${m.id}`}
                data-note={m.note}
                onClick={() => setMode(m.id)}
                className={`relative font-mono text-[10px] tracking-[0.14em] uppercase px-2 py-1.5 transition-colors ${
                  on ? "text-ink" : "text-faint hover:text-mute"
                }`}
              >
                <span className={`absolute left-1/2 -translate-x-1/2 top-0 w-1 h-1 rounded-full bg-signal transition-transform duration-300 ${
                  on ? "scale-100" : "scale-0"
                }`} />
                {m.id}
              </button>
            );
          })}
        </div>

        <span className="flex-1 sm:hidden" />

        {busy ? (
          <button
            data-testid="stop"
            onClick={() => running && stop(running.key)}
            aria-label="stop this run"
            data-note="stop this run"
            className="shrink-0 w-10 h-10 rounded-full border border-signal text-signal grid place-items-center hover:bg-signal hover:text-ground transition-colors"
          >
            <span className="w-[9px] h-[9px] bg-current" />
          </button>
        ) : (
          <button
            data-testid="ask"
            onClick={submit}
            disabled={!q.trim()}
            aria-label="ask"
            className="shrink-0 w-10 h-10 rounded-full grid place-items-center bg-ink text-ground transition
                       hover:bg-signal disabled:bg-transparent disabled:text-faint disabled:border disabled:border-line-2"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden>
              <path d="M2 7h10M8 3l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        )}
      </div>
    </div>
  );
}
