import { useChat } from "../state/chat";

/* Conversation list. Every question you have asked, grouped into threads; click one to read it
   again or ask a follow-up inside it. */

function when(ts: number): string {
  const mins = Math.floor((Date.now() - ts) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return days === 1 ? "yesterday" : `${days}d ago`;
}

export function Threads({ open, onNavigate }: { open: boolean; onNavigate?: () => void }) {
  const threads = useChat((s) => s.threads);
  const activeId = useChat((s) => s.activeId);
  const { openThread, newThread, deleteThread } = useChat();

  if (!open) return null;

  return (
    <nav className="w-[248px] shrink-0 border-r border-[var(--rule)] flex flex-col h-dvh sticky top-0">
      <div className="px-4 h-[68px] flex items-center">
        <button
          onClick={() => { newThread(); onNavigate?.(); }}
          className="font-mono text-[10px] tracking-[0.16em] uppercase px-3 py-1.5 border border-[var(--rule-2)] text-paper hover:border-amber hover:text-amber transition-colors w-full"
        >
          + new question
        </button>
      </div>

      <div className="label px-4 pb-2">history</div>

      <div className="flex-1 overflow-y-auto pb-4">
        {threads.length === 0 && (
          <div className="px-4 text-[12.5px] text-slate leading-relaxed">
            Nothing yet. Your questions will collect here.
          </div>
        )}
        {threads.map((t) => (
          <div key={t.id} className="group relative">
            <button
              onClick={() => { openThread(t.id); onNavigate?.(); }}
              className={`w-full text-left px-4 py-2.5 border-l-2 transition-colors ${
                t.id === activeId
                  ? "border-amber bg-[var(--ground-2)]"
                  : "border-transparent hover:bg-[var(--ground-2)]"
              }`}
            >
              <div className={`text-[13px] leading-snug line-clamp-2 pr-5 ${
                t.id === activeId ? "text-paper" : "text-paper/70"
              }`}>
                {t.title}
              </div>
              <div className="label !text-[9px] mt-1">
                {when(t.updated)}
                {t.exchanges.length > 1 && ` · ${t.exchanges.length} questions`}
              </div>
            </button>
            <button
              onClick={() => deleteThread(t.id)}
              data-note="delete this conversation"
              className="absolute top-2.5 right-2 opacity-0 group-hover:opacity-100 label hover:!text-amber transition-opacity"
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </nav>
  );
}
