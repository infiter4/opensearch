import { useEffect, useState } from "react";
import { useChat } from "../state/chat";

/* The actual page, with the matched quote located inside it. The span is found by plain string
   search, the same way the checker found it. That is the receipt: not "trust me", but here is the
   sentence, in the page, where I said it was. */

export function SourceDrawer() {
  const { openSource, closeSource } = useChat();
  const threads = useChat((s) => s.threads);
  const [body, setBody] = useState<{ title: string; url: string; content: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // Search every thread, not just the active one — the drawer outlives a thread switch.
  const ex = threads.flatMap((t) => t.exchanges).find((e) => e.key === openSource?.exKey);

  useEffect(() => {
    setBody(null); setErr(null);
    if (!openSource || !ex?.queryId) return;
    fetch(`/api/source/${openSource.id}?query_id=${ex.queryId}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setBody)
      .catch((e) => setErr(String(e.message ?? e)));
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
      <div className="fixed inset-0 z-40 bg-[#0B1015]/70" onClick={closeSource} />
      <aside className="fixed right-0 top-0 bottom-0 z-50 w-[min(600px,94vw)] bg-ground-2 border-l border-[var(--rule-2)] flex flex-col tick">
        <header className="px-7 pt-5 pb-4 rule-b">
          <div className="flex items-start justify-between gap-4">
            <div className="label">
              source {openSource.id} · {meta?.domain?.replace(/^www\./, "")}
            </div>
            <button className="label hover:!text-paper" onClick={closeSource}>close ✕</button>
          </div>
          <h3 className="text-[18px] leading-snug mt-2">{body?.title || meta?.title}</h3>
          <div className="label mt-2">
            {words ? `${Number(words).toLocaleString()} words · ` : ""}
            {quotesHere} quote{quotesHere === 1 ? "" : "s"} matched
          </div>
          <a className="font-mono text-[10px] text-amber break-all mt-1.5 block" href={meta?.url}
             target="_blank" rel="noreferrer">
            {meta?.url}
          </a>
        </header>

        {openSource.quote && (
          <div className="label px-7 py-2 rule-b !text-amber">
            matched quote — found by exact text search ↓
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-7 py-5 text-[13.5px] leading-[1.8] text-paper/70 whitespace-pre-wrap">
          {err && <div className="font-mono text-[12px] text-amber">could not load this source: {err}</div>}
          {!err && !body && <div className="label live-dot">loading source…</div>}
          {content}
        </div>
      </aside>
    </>
  );
}
