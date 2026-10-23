import { useEffect, useState } from "react";
import { isLive, type Exchange } from "../state/chat";

/* What is actually happening, with a denominator.
   Checking is the long pole: a deep run extracts ~350 claims and checks each against the page it
   cites, six at a time. Without a total, "71 checked" reads as stuck rather than 20% done. And
   when the provider rate-limits, the retry ladder backs off silently (2/4/8/16/32s) — so a live
   "no response for Ns" line is the difference between a wedged app and a working one. */

const STALL_S = 12;

export function Progress({ ex }: { ex: Exchange }) {
  const [, tick] = useState(0);
  const running = isLive(ex.phase);

  // Re-render on a timer: the stall counter is time-based, not event-based. Nothing else would
  // wake this component while the provider is silent — which is precisely when it matters.
  useEffect(() => {
    if (!running) return;
    const h = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(h);
  }, [running]);

  const totalClaims = Object.values(ex.claimsBy).reduce((a, c) => a + c.length, 0);
  const checked = new Set(Object.values(ex.checks).map((c) => c.claim_id)).size;
  const pct = totalClaims ? Math.min(100, Math.round((checked / totalClaims) * 100)) : 0;
  const quiet = Math.round((Date.now() - ex.lastAt) / 1000);
  const stalled = running && quiet >= STALL_S;
  const lastWarn = [...(ex.log ?? [])].reverse().find((e) => e.kind === "warn");

  const stage =
    ex.phase === "researching" ? "searching and reading"
    : ex.phase === "checking" ? "checking claims"
    : ex.phase === "repairing" ? "correcting"
    : ex.phase === "writing" ? "writing"
    : "done";

  return (
    <div data-testid="progress" className="space-y-4">
      <div className="flex items-center gap-3">
        {running && <Orbit />}
        <span className="text-[16px] italic">{stage}</span>
      </div>

      <div className="label !text-faint">{Object.keys(ex.sources).length} sources</div>

      {totalClaims > 0 && (
        <div className="space-y-2">
          <div className="flex items-baseline justify-between font-mono text-[11px] text-ink/80 tabular-nums">
            <span>{checked} / {totalClaims} claims</span>
            <span className="text-faint">{pct}%</span>
          </div>
          {/* A line, not a spinner: a spinner tells you nothing, a line tells you where you are. */}
          <div className="relative h-px bg-line-2 w-full">
            <div className="absolute left-0 -top-px h-[3px] bg-signal transition-[width] duration-700" style={{ width: `${pct}%` }} />
            <div className="absolute -top-[3px] w-[7px] h-[7px] rounded-full bg-signal -translate-x-1/2 transition-[left] duration-700"
                 style={{ left: `${pct}%` }} />
          </div>
        </div>
      )}

      {!totalClaims && running && (
        <div className="font-mono text-[11px] text-mute">{Object.keys(ex.checks).length} checked</div>
      )}

      {ex.repairing.size > 0 && (
        <div className="label !text-signal !text-[9px]">{ex.repairing.size} being corrected</div>
      )}

      {stalled && (
        <div className="pt-1 min-w-0">
          <div className="label !text-signal">no response for {quiet}s</div>
          {/* The provider error, verbatim but CONTAINED. A 429 body is long and unbroken; without
              min-w-0 + wrapping + a line clamp it spilled over the answer beside it. */}
          {lastWarn ? (
            <div
              className="font-mono text-[10px] text-signal/80 mt-1.5 leading-relaxed line-clamp-4 overflow-hidden break-words [overflow-wrap:anywhere]"
              data-note={lastWarn.what}
            >
              {lastWarn.what}
            </div>
          ) : (
            <div className="text-[13px] italic text-mute mt-1">waiting on the provider — retrying with backoff</div>
          )}
        </div>
      )}
    </div>
  );
}

/** A point circling a ring: alive, without pretending to know how long. */
function Orbit() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden className="shrink-0">
      <circle cx="8" cy="8" r="6" fill="none" stroke="var(--line-2)" strokeWidth="1" />
      <g className="spin" style={{ transformOrigin: "8px 8px", transformBox: "view-box" }}>
        <circle cx="8" cy="2" r="2" fill="var(--signal)" />
      </g>
    </svg>
  );
}
