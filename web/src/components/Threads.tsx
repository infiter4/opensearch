import { useChat } from "../state/chat";

/* Conversation list. Every question you have asked, grouped into threads; click one to read it
   again or ask a follow-up inside it. Beside the page on wide screens, over it on narrow ones. */

function when(ts: number): string {
  const mins = Math.floor((Date.now() - ts) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return days === 1 ? "yesterday" : `${days}d ago`;
}

export function Threads({ open, onNavigate, onClose }: {
  open: boolean; onNavigate?: () => void; onClose?: () => void;
}) {
  const threads = useChat((s) => s.threads);
  const activeId = useChat((s) => s.activeId);
  const openThread = useChat((s) => s.openThread);
  const newThread = useChat((s) => s.newThread);
  const deleteThread = useChat((s) => s.deleteThread);

  if (!open) return null;

  return (
    <>
      <div className="fixed inset-0 z-40 bg-[var(--scrim)] backdrop-blur-[2px] lg:hidden fade" onClick={onClose} />
      <nav
        data-testid="threads"
        className="fixed inset-y-0 left-0 z-50 w-[276px] bg-ground border-r border-line flex flex-col h-dvh shrink-0 slide-in-left
                   lg:sticky lg:top-0 lg:z-auto lg:animate-none"
      >
        <div className="px-5 h-[64px] flex items-center">
          <button
            data-testid="new-thread"
            onClick={() => { newThread(); onNavigate?.(); }}
            className="group flex items-center gap-3 label hover:!text-ink transition-colors"
          >
            <span className="w-6 h-6 rounded-full border border-line-2 grid place-items-center group-hover:border-ink transition-colors">
              <svg width="9" height="9" viewBox="0 0 9 9" aria-hidden>
                <path d="M4.5 0.5v8M0.5 4.5h8" stroke="currentColor" strokeWidth="1.1" />
              </svg>
            </span>
            new question
          </button>
        </div>

        <div className="label !text-faint px-5 pt-2 pb-3">history</div>

        <div className="flex-1 overflow-y-auto pb-6">
          {threads.length === 0 && (
            <div className="px-5 text-[14px] italic text-mute leading-relaxed">
              Nothing yet. Your questions will collect here.
            </div>
          )}
          {threads.map((t) => {
            const on = t.id === activeId;
            return (
              <div key={t.id} className="group relative">
                <button
                  data-testid="thread"
                  data-active={on}
                  onClick={() => { openThread(t.id); onNavigate?.(); }}
                  className="w-full text-left pl-11 pr-10 py-3 transition-colors hover:bg-raised/60"
                >
                  <span
                    className={`absolute left-5 top-[19px] w-[7px] h-[7px] rounded-full transition-colors ${
                      on ? "bg-signal" : "border border-faint group-hover:border-ink"
                    }`}
                  />
                  <div className={`text-[14.5px] leading-snug line-clamp-2 transition-colors ${
                    on ? "text-ink" : "text-ink/65 group-hover:text-ink"
                  }`}>
                    {t.title}
                  </div>
                  <div className="label !text-[9px] !text-faint mt-1.5">
                    {when(t.updated)}
                    {t.exchanges.length > 1 && ` · ${t.exchanges.length} questions`}
                  </div>
                </button>
                <button
                  data-testid="thread-delete"
                  onClick={() => deleteThread(t.id)}
                  aria-label="delete this conversation"
                  data-note="delete this conversation"
                  className="absolute top-3 right-3 w-6 h-6 grid place-items-center rounded-full text-faint hover:text-signal hover:bg-raised
                             opacity-0 group-hover:opacity-100 focus-visible:opacity-100 [@media(hover:none)]:opacity-70 transition"
                >
                  <svg width="8" height="8" viewBox="0 0 8 8" aria-hidden>
                    <path d="M1 1l6 6M7 1 1 7" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
                  </svg>
                </button>
              </div>
            );
          })}
        </div>
      </nav>
    </>
  );
}
