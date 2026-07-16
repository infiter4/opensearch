import { useEffect, useState } from "react";
import type { Exchange } from "../state/chat";

/* What is actually happening, with a denominator.
   Checking is the long pole: a deep run extracts ~350 claims and checks each against the page it
   cites, six at a time. Without a total, "71 checked" reads as stuck rather than 20% done. And
   when the provider rate-limits, the retry ladder backs off silently (2/4/8/16/32s) — so a live
   "no response for Ns" line is the difference between a wedged app and a working one. */

const STALL_S = 12;

export function Progress({ ex }: { ex: Exchange }) {
  const [, tick] = useState(0);
  const running = ex.phase !== "done" && ex.phase !== "error";

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
    <div className="space-y-2">
      <div className="label">{stage}</div>

      <div className="label !text-[9px] text-slate">
        {Object.keys(ex.sources).length} sources
      </div>

      {totalClaims > 0 && (
        <>
          <div className="font-mono text-[11px] text-paper/80">
            {checked} / {totalClaims} claims
          </div>
          {/* A bar, not a spinner: a spinner tells you nothing, a bar tells you where you are. */}
          <div className="h-[3px] bg-[var(--rule)] w-full">
            <div
              className="h-full bg-amber transition-[width] duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>
          <div className="label !text-[9px]">{pct}% checked</div>
        </>
      )}

      {!totalClaims && running && (
        <div className="font-mono text-[11px] text-slate">
          {Object.keys(ex.checks).length} checked
        </div>
      )}

      {ex.repairing.size > 0 && (
        <div className="label !text-amber !text-[9px]">{ex.repairing.size} being corrected</div>
      )}

      {stalled && (
        <div className="pt-1 min-w-0">
          <div className="label !text-amber">no response for {quiet}s</div>
          {/* The provider error, verbatim but CONTAINED. A 429 body is long and unbroken; without
              min-w-0 + wrapping + a line clamp it spilled over the answer beside it. */}
          {lastWarn ? (
            <div
              className="font-mono text-[9.5px] text-amber/80 mt-1 leading-relaxed line-clamp-4 overflow-hidden break-words [overflow-wrap:anywhere]"
              data-note={lastWarn.what}
            >
              {lastWarn.what}
            </div>
          ) : (
            <div className="label text-slate mt-1">waiting on the provider — retrying with backoff</div>
          )}
        </div>
      )}
    </div>
  );
}
