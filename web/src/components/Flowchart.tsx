import { useEffect, useMemo, useState } from "react";
import type { Exchange } from "../state/chat";

/* The ANSWER as a flowchart: the same extracted entities and relationships as the 3D graph, laid
 * out as a readable tree instead of a cloud. Same data, two senses — the graph is for exploring,
 * this is for reading and for a screenshot.
 *
 * Hand-rolled SVG: a layout library for a tree this small is a dependency and a build risk. */

interface Node { id: string; label: string; type: string }
interface Link { source: string; target: string; label: string }
interface Concept { nodes: Node[]; links: Link[]; pending?: boolean }

const TONE: Record<string, string> = {
  root: "#E0912A", entity: "#E7E1D4", value: "#7FB2C4", concept: "#8A94A0",
};

const COL_W = 250;
const ROW_H = 34;
const PAD = 14;

export function Flowchart({ ex }: { ex: Exchange }) {
  const [data, setData] = useState<Concept | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!ex.queryId) { setErr("this conversation is too old to chart — ask again"); return; }
    let dead = false;
    fetch(`/api/concept?query_id=${ex.queryId}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => { if (!dead) setData(d); })
      .catch((e) => { if (!dead) setErr(String(e.message ?? e)); });
    return () => { dead = true; };
  }, [ex.queryId]);

  /** Breadth-first from the root: depth = column, order within depth = row. */
  const laid = useMemo(() => {
    if (!data?.nodes?.length) return null;
    const byId = new Map(data.nodes.map((n) => [n.id, n]));
    const out = new Map<string, string[]>();
    for (const l of data.links) {
      if (!out.has(l.source)) out.set(l.source, []);
      out.get(l.source)!.push(l.target);
    }
    const root = data.nodes.find((n) => n.type === "root") ?? data.nodes[0];
    const depth = new Map<string, number>([[root.id, 0]]);
    const queue = [root.id];
    // BFS, not DFS: a node's column must be its SHORTEST distance from the root, or one shortcut
    // edge drags it right and the chart stops reading left-to-right.
    while (queue.length) {
      const id = queue.shift()!;
      for (const t of out.get(id) ?? []) {
        if (depth.has(t) || !byId.has(t)) continue;
        depth.set(t, depth.get(id)! + 1);
        queue.push(t);
      }
    }
    for (const n of data.nodes) if (!depth.has(n.id)) depth.set(n.id, 1);   // unreachable → col 1

    const cols = new Map<number, string[]>();
    for (const n of data.nodes) {
      const d = depth.get(n.id)!;
      if (!cols.has(d)) cols.set(d, []);
      cols.get(d)!.push(n.id);
    }
    const pos = new Map<string, { x: number; y: number }>();
    let maxRows = 0;
    for (const [d, ids] of [...cols].sort((a, b) => a[0] - b[0])) {
      maxRows = Math.max(maxRows, ids.length);
      ids.forEach((id, i) => pos.set(id, { x: PAD + d * COL_W, y: PAD + i * ROW_H + ROW_H / 2 }));
    }
    return {
      byId, pos,
      w: PAD * 2 + (Math.max(...cols.keys()) + 1) * COL_W,
      h: PAD * 2 + maxRows * ROW_H,
      links: data.links.filter((l) => pos.has(l.source) && pos.has(l.target)),
    };
  }, [data]);

  if (err) return <div className="label !text-amber">could not build the chart: {err}</div>;
  if (!data) return <div className="label live-dot">reading the answer…</div>;
  if (data.pending) return <div className="label">the answer is not finished yet</div>;
  if (!laid) return <div className="label">nothing to chart in this answer</div>;

  const BOX_W = COL_W - 60;

  return (
    <div className="overflow-x-auto">
      <div className="label mb-2">{data.nodes.length} things · {data.links.length} relationships</div>
      <svg viewBox={`0 0 ${laid.w} ${laid.h}`} width="100%" height={laid.h}
           style={{ minWidth: Math.min(laid.w, 900) }}>
        <defs>
          <marker id="fc-arr" viewBox="0 0 8 8" refX={7} refY={4} markerWidth={6} markerHeight={6} orient="auto">
            <path d="M 0 0 L 8 4 L 0 8 z" fill="rgba(231,225,212,0.4)" />
          </marker>
        </defs>

        {laid.links.map((l, i) => {
          const a = laid.pos.get(l.source)!, b = laid.pos.get(l.target)!;
          const x1 = a.x + BOX_W, x2 = b.x;
          // Diagonal bezier — an orthogonal elbow reads as a wiring diagram, not a knowledge map.
          const d = `M ${x1} ${a.y} C ${x1 + 34} ${a.y}, ${x2 - 34} ${b.y}, ${x2} ${b.y}`;
          return (
            <g key={i}>
              <path d={d} fill="none" stroke="rgba(231,225,212,0.22)" strokeWidth={1.2}
                    markerEnd="url(#fc-arr)" />
              {l.label && (
                <text x={(x1 + x2) / 2} y={(a.y + b.y) / 2 - 4} textAnchor="middle"
                      fontSize={8} fill="var(--slate)" fontFamily="var(--font-mono)">
                  {l.label}
                </text>
              )}
            </g>
          );
        })}

        {[...laid.pos].map(([id, p]) => {
          const n = laid.byId.get(id)!;
          const tone = TONE[n.type] ?? "#8A94A0";
          return (
            <g key={id}>
              <rect x={p.x} y={p.y - 11} width={BOX_W} height={22} rx={3}
                    fill="var(--ground-2)" stroke={n.type === "root" ? tone : "var(--rule-2)"}
                    strokeWidth={n.type === "root" ? 1.4 : 1} />
              <text x={p.x + 8} y={p.y + 3.5} fontSize={9.5} fill={tone}
                    fontFamily="var(--font-mono)" fontWeight={n.type === "root" ? 700 : 400}>
                {n.label.length > 30 ? n.label.slice(0, 29) + "…" : n.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
