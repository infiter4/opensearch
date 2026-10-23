import type { TrustTally, Verdict } from "./protocol";

/* The verdict vocabulary as geometry. Shape carries the meaning; red only marks trouble.
     verified      ■ filled          thin       ◧ half
     unsupported   □ hollow          contradicted ◆ red diamond
     withdrawn     ⟋ red slash       checking   · a point                                     */

export function VerdictShape({ v, size = 10 }: { v: Verdict; size?: number }) {
  const common = { width: size, height: size, viewBox: "0 0 10 10", "aria-hidden": true, className: "shrink-0" };
  switch (v) {
    case "supported":
      return <svg {...common}><rect x="1.5" y="1.5" width="7" height="7" fill="currentColor" /></svg>;
    case "weak":
      return (
        <svg {...common}>
          <rect x="2" y="2" width="6" height="6" fill="none" stroke="currentColor" />
          <rect x="1.5" y="1.5" width="3.5" height="7" fill="currentColor" />
        </svg>
      );
    case "unsupported":
      return <svg {...common}><rect x="2" y="2" width="6" height="6" fill="none" stroke="currentColor" /></svg>;
    case "contradicted":
      return <svg {...common}><path d="M5 0.6 9.4 5 5 9.4 0.6 5Z" fill="var(--signal)" /></svg>;
    case "retracted":
      return <svg {...common}><path d="M1.5 8.5 8.5 1.5" stroke="var(--signal)" strokeWidth="1.5" strokeLinecap="round" /></svg>;
    default:
      return <svg {...common}><circle cx="5" cy="5" r="1.2" fill="currentColor" opacity="0.45" /></svg>;
  }
}

const ORDER: Verdict[] = ["supported", "weak", "unsupported", "contradicted", "retracted"];

/** How each verdict's arc is drawn — the same five line styles the marks under the prose use. */
const STROKE: Record<string, { color: string; width: number; dash?: string; cap?: "round" | "butt"; double?: boolean }> = {
  supported: { color: "var(--ink)", width: 3 },
  weak: { color: "var(--ink)", width: 3, dash: "5 3.5" },
  unsupported: { color: "var(--ink)", width: 3, dash: "0.01 5.5", cap: "round" },
  contradicted: { color: "var(--signal)", width: 1.1, double: true },
  retracted: { color: "var(--signal)", width: 3, dash: "9 2.5 1.5 2.5" },
};

const polar = (r: number, a: number) => [66 + r * Math.cos(a), 66 + r * Math.sin(a)];
function arc(r: number, a0: number, a1: number): string {
  const [x0, y0] = polar(r, a0);
  const [x1, y1] = polar(r, a1);
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

/** The tally drawn as a figure: one ring, cut into arcs by verdict, each arc in its own line style.
 *  The share of trouble is visible at a glance and still readable without colour. A red point sits
 *  where the trouble begins — the one place the eye should go. */
export function Sigil({ t, size = 132 }: { t: TrustTally; size?: number }) {
  const total = ORDER.reduce((a, v) => a + (t[v as keyof TrustTally] as number), 0);
  const R = 52;
  const gap = total > 1 ? 0.07 : 0;
  let a = -Math.PI / 2;
  let troubleAt: number | null = null;
  const arcs = total
    ? ORDER.filter((v) => (t[v as keyof TrustTally] as number) > 0).map((v, i) => {
        const span = ((t[v as keyof TrustTally] as number) / total) * Math.PI * 2;
        const seg = { v, a0: a + gap / 2, a1: a + Math.max(span - gap / 2, gap / 2 + 0.02), i };
        if (troubleAt == null && (v === "unsupported" || v === "contradicted" || v === "retracted")) troubleAt = a;
        a += span;
        return seg;
      })
    : [];
  const full = arcs.length === 1 && !gap;

  return (
    <svg viewBox="0 0 132 132" width={size} height={size} aria-hidden className="overflow-visible">
      <circle cx="66" cy="66" r={R} fill="none" stroke="var(--line)" strokeWidth="1" />
      <circle cx="66" cy="66" r={R - 14} fill="none" stroke="var(--line)" strokeWidth="1" strokeDasharray="1 4" />
      {arcs.map((s) => {
        const st = STROKE[s.v];
        const style = { animationDelay: `${120 + s.i * 110}ms` };
        const one = (r: number, key: string) =>
          full ? (
            <circle key={key} cx="66" cy="66" r={r} fill="none" stroke={st.color} strokeWidth={st.width}
                    strokeDasharray={st.dash} strokeLinecap={st.cap ?? "butt"} className="fade" style={style} />
          ) : (
            <path key={key} d={arc(r, s.a0, s.a1)} fill="none" stroke={st.color} strokeWidth={st.width}
                  strokeDasharray={st.dash} strokeLinecap={st.cap ?? "butt"} className="fade" style={style} />
          );
        return st.double ? [one(R - 2.2, `${s.v}a`), one(R + 2.2, `${s.v}b`)] : one(R, s.v);
      })}
      {troubleAt != null && (() => {
        const [x, y] = polar(R + 11, troubleAt);
        return <circle cx={x} cy={y} r="3.2" fill="var(--signal)" className="fade" style={{ animationDelay: "700ms" }} />;
      })()}
    </svg>
  );
}
