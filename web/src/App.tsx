import { useEffect, useRef, useState } from "react";
import { Boundary } from "./components/Boundary";
import { Composer } from "./components/Composer";
import { ExchangeView } from "./components/ExchangeView";
import { SourceDrawer } from "./components/SourceDrawer";
import { Threads } from "./components/Threads";
import { activeExchanges, useChat } from "./state/chat";

export default function App() {
  const exchanges = useChat(activeExchanges);
  const nThreads = useChat((s) => s.threads.length);
  const [sidebar, setSidebar] = useState(true);
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [exchanges.length]);

  // Re-attach to runs that were in flight when the page went away. Once, on mount.
  useEffect(() => { useChat.getState().reattach(); }, []);

  return (
    <div className="min-h-dvh flex">
      <Threads open={sidebar} />

      <div className="flex-1 min-w-0 flex flex-col">
        <header className="sticky top-0 z-30 bg-ground/95 backdrop-blur-sm rule-b">
          <div className="max-w-[1000px] mx-auto px-11 h-[68px] flex items-center gap-5">
            <button
              onClick={() => setSidebar((v) => !v)}
              data-note={sidebar ? "hide history" : "show history"}
              className="label hover:!text-paper shrink-0"
            >
              ☰
            </button>
            <span className="flex items-baseline">
              <span className="text-[22px] tracking-[-0.3px]">receipts</span>
              <span className="text-amber text-[30px] leading-none relative top-[5px]">*</span>
            </span>
            <span className="flex-1" />
            <span className="label hidden sm:block">every claim checked against its source</span>
          </div>
        </header>

        <main className="flex-1 w-full max-w-[1000px] mx-auto px-11 min-w-0">
          {exchanges.length === 0 && <Empty hasHistory={nThreads > 0} />}
          {exchanges.map((ex, i) => (
            <Boundary key={ex.key}>
              <ExchangeView ex={ex} index={i} />
            </Boundary>
          ))}
          <div ref={endRef} className="h-2" />
        </main>

        <footer className="sticky bottom-0 z-30 bg-ground/95 backdrop-blur-sm rule-t">
          <div className="max-w-[1000px] mx-auto px-11 py-4">
            <Composer />
          </div>
        </footer>
      </div>

      <SourceDrawer />
    </div>
  );
}

const OPENERS: { q: string; tag: string; mode: string }[] = [
  { q: "What are the rate limits of Ollama's web search API?", tag: "well documented", mode: "lite" },
  { q: "How much does Tavily's search API cost and what does the free tier include?", tag: "often misreported", mode: "pro" },
  { q: "Do AI search engines cite sources accurately?", tag: "the sources disagree", mode: "deep" },
];

function Empty({ hasHistory }: { hasHistory: boolean }) {
  const ask = useChat((s) => s.ask);
  return (
    <div className="pt-[14vh] pb-12 max-w-[760px] mx-auto">
      <p className="text-[38px] leading-[1.22] text-balance">
        Every answer is{" "}
        <span className="mk mk-contradicted">checked</span> against the sources it cites.
      </p>
      <p className="text-[15px] text-slate mt-6 leading-[1.8] max-w-[58ch]">
        Research agents search the web and cite what they find. Then a separate model — one that
        never sees your question — checks every sentence against the page it cites, and must quote
        the words that support it. Claims that check out are kept. Claims that don&rsquo;t are
        corrected, or withdrawn and shown to you anyway.
      </p>

      <div className="label mt-16 mb-2">{hasHistory ? "ask something new" : "try a question"}</div>
      <div className="rule-t">
        {OPENERS.map((o) => (
          <button
            key={o.q}
            onClick={() => void ask(o.q, o.mode)}
            className="group w-full text-left py-4 px-2 -mx-2 rule-b flex items-baseline gap-5 hover:bg-[var(--ground-2)] transition-colors"
          >
            <span className="label shrink-0 w-10">{o.mode}</span>
            <span className="text-[15.5px] text-paper/80 group-hover:text-paper flex-1 leading-snug">{o.q}</span>
            <span className="label !text-[9px] shrink-0 hidden md:block text-right">{o.tag}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
