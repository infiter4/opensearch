import { useEffect, useRef } from "react";
import { Composer } from "./components/Composer";
import { ExchangeView } from "./components/ExchangeView";
import { SourceDrawer } from "./components/SourceDrawer";
import { useChat } from "./state/chat";

export default function App() {
  const exchanges = useChat((s) => s.exchanges);
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [exchanges.length]);

  return (
    <div className="min-h-dvh flex flex-col">
      <header className="sticky top-0 z-30 bg-ground/95 backdrop-blur-sm rule-b">
        <div className="max-w-[1000px] mx-auto px-11 h-[68px] flex items-center gap-8">
          <span className="flex items-baseline">
            <span className="text-[22px] tracking-[-0.3px]">receipts</span>
            <span className="text-amber text-[30px] leading-none relative top-[5px]">*</span>
          </span>
          <span className="flex-1" />
          <span className="label hidden sm:block">everyone cites · we cross-examine</span>
        </div>
      </header>

      <main className="flex-1 w-full max-w-[1000px] mx-auto px-11">
        {exchanges.length === 0 && <Empty />}
        {exchanges.map((ex, i) => <ExchangeView key={ex.key} ex={ex} index={i} />)}
        <div ref={endRef} className="h-2" />
      </main>

      <footer className="sticky bottom-0 z-30 bg-ground/95 backdrop-blur-sm rule-t">
        <div className="max-w-[1000px] mx-auto px-11 py-4">
          <Composer />
        </div>
      </footer>

      <SourceDrawer />
    </div>
  );
}

const OPENERS: { q: string; tag: string; mode: string }[] = [
  { q: "What are the rate limits of Ollama's web search API?", tag: "well documented", mode: "lite" },
  { q: "How much does Tavily's search API cost and what does the free tier include?", tag: "blogspam gets this wrong", mode: "pro" },
  { q: "Do AI search engines cite sources accurately?", tag: "the sources disagree", mode: "deep" },
];

function Empty() {
  const ask = useChat((s) => s.ask);
  return (
    <div className="pt-[16vh] pb-12 max-w-[760px] mx-auto">
      <p className="text-[38px] leading-[1.22] text-balance">
        Every answer here has been{" "}
        <span className="mk mk-contradicted">cross-examined</span> against its own sources.
      </p>
      <p className="text-[15px] text-slate mt-6 leading-[1.8] max-w-[58ch]">
        Researchers work the angles and pin quotes. Then an independent model — one that never sees
        the question — checks every sentence against the page it cites. What holds up is shipped.
        What doesn&rsquo;t is corrected, or withdrawn and shown to you anyway.
      </p>

      <div className="label mt-16 mb-2">start a case</div>
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
