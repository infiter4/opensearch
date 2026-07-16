import { useMemo } from "react";
import type { Exchange } from "../state/chat";

/* The run as a flowchart: question → researchers → sources → the audit → the answer.
   Hand-rolled SVG over data the exchange already holds — every number on it is real. */

const LANE_H = 44;
const W = 860;

export function Flowchart({ ex }: { ex: Exchange }) {
  const model = useMemo(() => {
    const researchers = ex.order.map((id) => ex.researchers[id]).filter(Boolean);
    const srcCount = Object.keys(ex.sources).length;
    const checks = Object.values(ex.checks);
    const failed0 = new Set(
      Object.values(ex.draft)
        .filter((c) => c.verdict === "unsupported" || c.verdict === "contradicted")
        .map((c) => c.sentence_id),
    );
    return {
      researchers, srcCount,
      checked: checks.length,
      healed: ex.healed.size,
      retracted: ex.retracted.length,
      failed0: failed0.size,
      trust: ex.trust,
    };
  }, [ex]);

  const n = Math.max(model.researchers.length, 1);
  const H = Math.max(n * LANE_H + 40, 200);
  const midY = H / 2;
  const laneY = (i: number) => 30 + i * LANE_H + LANE_H / 2 - ((n * LANE_H) / 2) + midY - 20;

  const box = (x: number, y: number, w: number, title: string, sub: string, tone = "var(--paper)") => (
    <g key={`${x}-${y}-${title}`}>
      <rect x={x} y={y - 19} width={w} height={38} rx={3}
            fill="var(--ground-2)" stroke="var(--rule-2)" strokeWidth={1} />
      <text x={x + w / 2} y={y - 4} textAnchor="middle"
            fontSize={10.5} fontWeight={600} fill={tone} fontFamily="var(--font-mono)">
        {title}
      </text>
      <text x={x + w / 2} y={y + 10} textAnchor="middle"
            fontSize={8.5} fill="var(--slate)" fontFamily="var(--font-mono)">
        {sub}
      </text>
    </g>
  );

  const arrow = (x1: number, y1: number, x2: number, y2: number, tone = "var(--rule)") => (
    <path key={`${x1}${y1}${x2}${y2}`}
          d={`M ${x1} ${y1} C ${x1 + 26} ${y1}, ${x2 - 26} ${y2}, ${x2} ${y2}`}
          fill="none" stroke={tone} strokeWidth={1.4} markerEnd="url(#arr)" />
  );

  const t = model.trust;
  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ minWidth: 700 }}>
        <defs>
          <marker id="arr" viewBox="0 0 8 8" refX={7} refY={4} markerWidth={7} markerHeight={7} orient="auto">
            <path d="M 0 0 L 8 4 L 0 8 z" fill="var(--slate)" />
          </marker>
        </defs>

        {box(8, midY, 120, "QUESTION", "split by the planner")}
        {model.researchers.map((r, i) => arrow(128, midY, 168, laneY(i)))}

        {model.researchers.map((r, i) =>
          box(168, laneY(i), 150,
              (r.title || r.id).slice(0, 22).toUpperCase(),
              r.id === "rt" || (r as any).role === "red_team" ? "red team" : `${r.tools.length} tool calls`,
              (r as any).role === "red_team" ? "var(--amber)" : "var(--paper)"),
        )}
        {model.researchers.map((_, i) => arrow(318, laneY(i), 358, midY))}

        {box(358, midY, 118, `${model.srcCount} SOURCES`, "read + interned")}
        {arrow(476, midY, 512, midY)}

        {box(512, midY, 148, `${model.checked} CLAIM CHECKS`,
             `${model.failed0} failed the first draft`, model.failed0 ? "var(--amber)" : "var(--paper)")}
        {arrow(660, midY, 696, midY)}

        {box(696, midY, 152,
             t ? `${t.supported}/${t.total} HELD UP` : "ANSWER",
             `${model.healed} healed · ${model.retracted} withdrawn`,
             "var(--paper)")}
      </svg>
    </div>
  );
}
