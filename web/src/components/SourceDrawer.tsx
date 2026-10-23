import { useEffect, useState } from "react";
import { useChat } from "../state/chat";

/* The actual page, with the matched quote located inside it. The span is found by plain string
   search, the same way the checker found it. That is the receipt: not "trust me", but here is the
   sentence, in the page, where I said it was. */

export function SourceDrawer() {
  const openSource = useChat((s) => s.openSource);
  const closeSource = useChat((s) => s.closeSource);
  // Search every thread, not just the active one — the drawer outlives a thread switch.
  const ex = useChat((s) =>
    openSource ? s.threads.flatMap((t) => t.exchanges).find((e) => e.key === openSource.exKey) : undefined);
  const [body, setBody] = useState<{ title: string; url: string; content: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setBody(null); setErr(null);
    if (!openSource || !ex?.queryId) return;
    // Click two citations quickly and the first response can land second: drop any answer that
    // is no longer for the source on screen.
    let stale = false;
    fetch(`/api/source/${openSource.id}?query_id=${ex.queryId}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((b) => { if (!stale) setBody(b); })
      .catch((e) => { if (!stale) setErr(String(e.message ?? e)); });
    return () => { stale = true; };
  }, [openSource?.id, openSource?.exKey, ex?.queryId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeSource();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [closeSource]);

  if (!openSource || !ex) return null;
  const meta = ex.sources[openSource.id];
  const quotesHere = Object.values(ex.checks).filter(
    (c) => c.source_id === openSource.id && c.quote,
  ).length;

  let content: React.ReactNode = null;
  if (body) {
    const text = body.content ?? "";
    const q = openSource.quote;
    const at = q ? text.indexOf(q) : -1;
    content =
      at >= 0 && q ? (
        <>
          {text.slice(Math.max(0, at - 1100), at)}
          <mark ref={(el) => el?.scrollIntoView({ block: "center" })}>{q}</mark>
          {text.slice(at + q.length, at + q.length + 3500)}
        </>
      ) : (
        text.slice(0, 7000)
      );
  }

  // Only claim a word count when the page is actually in hand. Falling back to n_chars and calling
  // it "words" is how an empty drawer wore a confident header.
  const words = body?.content ? body.content.trim().split(/\s+/).length : null;

  return (
    <>
      <div data-testid="drawer-overlay" className="fixed inset-0 z-40 bg-[var(--scrim)] backdrop-blur-[2px] fade" onClick={closeSource} />
      <aside
        data-testid="drawer"
        role="dialog"
        aria-label={`source ${openSource.id}`}
        className="fixed right-0 top-0 bottom-0 z-50 w-[min(620px,100vw)] bg-ground border-l border-line-2 flex flex-col slide-in
                   shadow-[-24px_0_60px_-30px_rgb(0_0_0/0.35)]"
      >
        <header className="px-6 sm:px-8 pt-6 pb-5 rule-b">
          <div className="flex items-center justify-between gap-4">
            <div className="label flex items-center gap-2.5 min-w-0">
              <span className="w-[18px] h-[18px] rounded-full border border-signal text-signal grid place-items-center text-[9px] tracking-normal shrink-0">
                {openSource.id}
              </span>
              <span className="truncate">{meta?.domain?.replace(/^www\./, "")}</span>
            </div>
            <button data-testid="drawer-close" aria-label="close" onClick={closeSource}
                    className="w-8 h-8 -mr-2 rounded-full grid place-items-center text-mute hover:text-ink hover:bg-raised transition-colors">
              <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden>
                <path d="M1 1l8 8M9 1 1 9" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
              </svg>
            </button>
          </div>
          <h3 className="display font-[380] text-[22px] sm:text-[24px] leading-[1.2] tracking-[-0.01em] mt-3">
            {body?.title || meta?.title}
          </h3>
          <div className="label !text-faint mt-3">
            {words ? `${Number(words).toLocaleString()} words · ` : ""}
            {quotesHere} quote{quotesHere === 1 ? "" : "s"} matched
          </div>
          {meta?.url && (
            <a className="font-mono text-[10.5px] break-all mt-2 block" href={meta.url} target="_blank" rel="noreferrer">
              {meta.url}
            </a>
          )}
        </header>

        {openSource.quote && (
          <div className="label px-6 sm:px-8 py-2.5 rule-b !text-signal flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-signal" />
            matched quote — found by exact text search
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-6 sm:px-8 py-6 text-[15px] leading-[1.8] text-ink/70 whitespace-pre-wrap break-words">
          {err && <div className="font-mono text-[12px] text-signal">could not load this source: {err}</div>}
          {!err && !body && <div className="label live-dot">loading source…</div>}
          {content}
        </div>
      </aside>
    </>
  );
}
