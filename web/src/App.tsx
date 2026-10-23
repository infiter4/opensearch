import { useEffect, useRef, useState } from "react";
import { Boundary } from "./components/Boundary";
import { Composer } from "./components/Composer";
import { ExchangeView } from "./components/ExchangeView";
import { SourceDrawer } from "./components/SourceDrawer";
import { Threads } from "./components/Threads";
import { setTheme, useTheme } from "./lib/theme";
import { activeExchanges, useChat } from "./state/chat";

/** The sidebar sits beside the page when there is room, and over it when there is not. */
const WIDE = "(min-width: 1024px)";
const isWide = () => typeof matchMedia === "function" && matchMedia(WIDE).matches;

export default function App() {
  const exchanges = useChat(activeExchanges);
  const nThreads = useChat((s) => s.threads.length);
  const [sidebar, setSidebar] = useState(isWide);
  const endRef = useRef<HTMLDivElement>(null);
  // Follow a new question down the page — but only when there is one. Scrolling on mount pushed
  // the empty page's opening lines up under the header before anyone had touched anything.
  useEffect(() => {
    if (exchanges.length) endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [exchanges.length]);

  // Re-attach to runs that were in flight when the page went away. Once, on mount.
  useEffect(() => { useChat.getState().reattach(); }, []);

  return (
    <div className="min-h-dvh flex">
      <Threads
        open={sidebar}
        onClose={() => setSidebar(false)}
        onNavigate={() => { if (!isWide()) setSidebar(false); }}
      />

      <div className="flex-1 min-w-0 flex flex-col">
        <header className="sticky top-0 z-30 bg-ground/85 backdrop-blur-md">
          <div className="max-w-[1040px] mx-auto px-5 sm:px-8 lg:px-12 h-[64px] flex items-center gap-5">
            <button
              data-testid="toggle-sidebar"
              onClick={() => setSidebar((v) => !v)}
              aria-label={sidebar ? "hide history" : "show history"}
              data-note={sidebar ? "hide history" : "show history"}
              className="group -ml-1.5 w-8 h-8 grid place-items-center text-mute hover:text-ink transition-colors"
            >
              <svg width="18" height="12" viewBox="0 0 18 12" aria-hidden>
                <path d="M1 2h16M1 10h10" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
                <circle cx="15.5" cy="10" r="1.6" fill="var(--signal)" />
              </svg>
            </button>
            <Wordmark />
            <span className="flex-1" />
            <span className="label !text-faint hidden md:block">every claim, checked against its source</span>
            <ThemeToggle />
          </div>
        </header>

        <main className="flex-1 w-full max-w-[1040px] mx-auto px-5 sm:px-8 lg:px-12 min-w-0">
          {exchanges.length === 0 && <Empty hasHistory={nThreads > 0} />}
          {exchanges.map((ex, i) => (
            <Boundary key={ex.key}>
              <ExchangeView ex={ex} index={i} />
            </Boundary>
          ))}
          <div ref={endRef} className="h-4" />
        </main>

        <footer className="sticky bottom-0 z-30 bg-ground/90 backdrop-blur-md">
          <div className="max-w-[1040px] mx-auto px-5 sm:px-8 lg:px-12 pt-3 pb-4">
            <div className="rule-t pt-3">
              <Composer />
            </div>
          </div>
        </footer>
      </div>

      <SourceDrawer />
    </div>
  );
}

function Wordmark() {
  return (
    <span className="flex items-baseline select-none">
      <span className="display italic text-[23px] tracking-[-0.02em] font-[420]">receipts</span>
      <span className="ml-[3px] w-[6px] h-[6px] rounded-full bg-signal translate-y-[-1px]" />
    </span>
  );
}

function ThemeToggle() {
  const theme = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      data-testid="theme-toggle"
      onClick={() => setTheme(next)}
      aria-label={`switch to ${next}`}
      data-note={`switch to ${next}`}
      className="w-8 h-8 -mr-1.5 grid place-items-center text-mute hover:text-ink transition-colors"
    >
      {/* half a disc: the side that is lit is the theme you are in */}
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden
           className="transition-transform duration-500" style={{ transform: `rotate(${theme === "dark" ? 180 : 0}deg)` }}>
        <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" strokeWidth="1" />
        <path d="M8 1.5a6.5 6.5 0 0 1 0 13Z" fill="currentColor" />
      </svg>
    </button>
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
    <div data-testid="empty" className="relative overflow-x-clip pt-[9vh] sm:pt-[12vh] pb-16">
      <Figure />
      <div className="relative max-w-[720px]">
        <div className="label !text-faint rise" style={{ animationDelay: "60ms" }}>fact-checked research</div>
        <h1 className="display font-[300] text-[40px] sm:text-[56px] lg:text-[64px] leading-[1.08] tracking-[-0.025em] mt-5 text-balance rise"
            style={{ animationDelay: "140ms" }}>
          Every answer, <span className="mk mk-contradicted italic [text-underline-offset:0.12em]">checked</span> against the sources it cites.
        </h1>
        <p className="text-[17px] sm:text-[18px] text-mute mt-7 leading-[1.7] max-w-[54ch] rise" style={{ animationDelay: "240ms" }}>
          Research agents search the web and cite what they find. Then a separate model — one that
          never sees your question — checks every sentence against the page it cites, and must quote
          the words that support it. Claims that hold are kept. Claims that don&rsquo;t are corrected,
          or withdrawn and shown to you anyway.
        </p>
      </div>

      <div className="relative mt-14 sm:mt-20 max-w-[820px] rise" style={{ animationDelay: "360ms" }}>
        <div className="label mb-3">{hasHistory ? "ask something new" : "try a question"}</div>
        <div className="rule-t">
          {OPENERS.map((o) => (
            <button
              key={o.q}
              data-testid="opener"
              onClick={() => void ask(o.q, o.mode)}
              className="group w-full text-left py-4 rule-b flex items-baseline gap-4 sm:gap-6 transition-colors"
            >
              <span className="label shrink-0 w-10 group-hover:!text-ink transition-colors">{o.mode}</span>
              <span className="text-[16px] sm:text-[17px] text-ink/75 group-hover:text-ink flex-1 leading-snug transition-colors">
                {o.q}
              </span>
              <span className="label !text-[9px] !text-faint shrink-0 hidden md:block text-right">{o.tag}</span>
              <span className="shrink-0 self-center w-2 h-2 rounded-full bg-signal scale-0 group-hover:scale-100 transition-transform duration-300" />
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/** The product, drawn abstractly: a question (the ring), the sources it gathered (points), and the
 *  citations between them — each line in the style of the verdict it earned. Solid held, dashed
 *  was thin, dotted was never said, the red double line was contradicted. Then a vermilion disc
 *  for the one claim that did not survive. It turns, very slowly. */
function Figure() {
  const pts = Array.from({ length: 9 }, (_, i) => {
    const a = (-0.95 + i * 0.235) * Math.PI;
    return [380 + 150 * Math.cos(a), 260 + 150 * Math.sin(a)];
  });
  const hub = [380, 260];
  const styles: [number, string | undefined, string, number][] = [
    [1, undefined, "var(--ink)", 1],
    [3, "5 4", "var(--ink)", 1],
    [5, "0.01 5", "var(--ink)", 1.6],
    [7, undefined, "var(--signal)", 1],
  ];
  return (
    <svg
      viewBox="0 0 640 560"
      aria-hidden
      className="pointer-events-none absolute -right-16 -top-8 w-[300px] opacity-40
                 sm:-right-10 sm:top-0 sm:w-[500px] sm:opacity-80 lg:-right-6 lg:top-2 lg:w-[560px]"
    >
      <g className="drift">
        <circle cx="380" cy="260" r="150" fill="none" stroke="var(--line-2)" strokeWidth="1" />
        <circle cx="380" cy="260" r="232" fill="none" stroke="var(--line)" strokeWidth="1" strokeDasharray="1 6" />
        {styles.map(([i, dash, color, w]) => {
          const [x, y] = pts[i];
          const len = Math.hypot(x - hub[0], y - hub[1]);
          const line = (dx: number, dy: number, k: string) => (
            <line key={k} x1={hub[0] + dx} y1={hub[1] + dy} x2={x + dx} y2={y + dy} stroke={color} strokeWidth={w}
                  strokeDasharray={dash} strokeLinecap="round"
                  className={dash ? "fade" : "draw"} style={{ ["--len" as string]: len, animationDelay: `${400 + i * 120}ms` }} />
          );
          if (color === "var(--signal)") {
            const nx = -(y - hub[1]) / len * 2.2, ny = (x - hub[0]) / len * 2.2;
            return <g key={i}>{line(nx, ny, "a")}{line(-nx, -ny, "b")}</g>;
          }
          return line(0, 0, String(i));
        })}
        {pts.map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r={i === 7 ? 4 : 3} fill={i === 7 ? "var(--signal)" : "var(--ink)"}
                  className="fade" style={{ animationDelay: `${300 + i * 60}ms` }} />
        ))}
        <circle cx="380" cy="260" r="5" fill="var(--ink)" />
      </g>
      <circle cx="548" cy="398" r="38" fill="var(--signal)" className="fade" style={{ animationDelay: "900ms" }} />
      {/* On a phone the figure sits behind the headline; the bar would cut through the copy. */}
      <rect x="420" y="40" width="170" height="5" fill="var(--ink)" transform="rotate(-24 505 42)"
            className="fade hidden sm:block" style={{ animationDelay: "1050ms" }} />
    </svg>
  );
}
