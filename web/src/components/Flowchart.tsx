import { useEffect, useMemo, useState } from "react";
import type { Exchange } from "../state/chat";

/* The ANSWER as a flowchart: the same extracted entities and relationships as the 3D graph, laid
 * out as a readable tree instead of a cloud. Same data, two senses — the graph is for exploring,
 * this is for reading and for a screenshot.
 *
 * Drawn the way the rest of the page draws: a thing is a point, a relationship is a hairline.
 * Hand-rolled SVG: a layout library for a tree this small is a dependency and a build risk. */

interface Node { id: string; label: string; type: string }
interface Link { source: string; target: string; label: string }
interface Concept { nodes: Node[]; links: Link[]; pending?: boolean; error?: string }

const TONE: Record<string, string> = {
  root: "var(--signal)", entity: "var(--ink)", value: "var(--cobalt)", concept: "var(--mute)",
};

const COL_W = 236;
const ROW_H = 34;
const PAD = 18;

export function Flowchart({ ex }: { ex: Exchange }) {
  const [data, setData] = useState<Concept | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!ex.queryId) { setErr("this conversation is too old to chart — ask again"); return; }
    let dead = false;
    fetch(`/api/concept?query_id=${ex.queryId}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.status === 404 ? "the server no longer has this run — ask again to chart it" : `HTTP ${r.status}`))))
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

  if (err) return <div className="label !text-signal">could not build the chart: {err}</div>;
  if (!data) return <div className="label live-dot">reading the answer…</div>;
  if (data.pending) return <div className="label">the answer is not finished yet</div>;
  if (data.error) return <div className="label !text-signal">could not build the chart: {data.error} — reopen to try again</div>;
  if (!laid) return <div className="label">nothing to chart in this answer</div>;

  const TEXT_W = COL_W - 56;   // where a node's label ends and its outgoing line begins

  return (
    <div data-testid="flowchart" className="overflow-x-auto">
      <div className="label mb-3 flex flex-wrap items-center gap-x-5 gap-y-1">
        <span>{data.nodes.length} things · {data.links.length} relationships</span>
        <span className="flex-1" />
        <Key color="var(--signal)" label="subject" />
        <Key color="var(--ink)" label="entity" />
        <Key color="var(--cobalt)" label="value" />
      </div>
      <svg viewBox={`0 0 ${laid.w} ${laid.h}`} width="100%" height={laid.h}
           style={{ minWidth: Math.min(laid.w, 880) }} className="fade">
        {laid.links.map((l, i) => {
          const a = laid.pos.get(l.source)!, b = laid.pos.get(l.target)!;
          const x1 = a.x + TEXT_W, x2 = b.x - 8;
          // Diagonal bezier — an orthogonal elbow reads as a wiring diagram, not a knowledge map.
          const d = `M ${x1} ${a.y} C ${x1 + 40} ${a.y}, ${x2 - 40} ${b.y}, ${x2} ${b.y}`;
          return (
            <g key={i}>
              <path d={d} fill="none" stroke="var(--line-2)" strokeWidth={1} />
              {l.label && (
                <text x={(x1 + x2) / 2} y={(a.y + b.y) / 2 - 5} textAnchor="middle"
                      fontSize={8.5} fill="var(--faint)" fontFamily="var(--font-mono)">
                  {l.label}
                </text>
              )}
            </g>
          );
        })}

        {[...laid.pos].map(([id, p]) => {
          const n = laid.byId.get(id)!;
          const tone = TONE[n.type] ?? "var(--mute)";
          const root = n.type === "root";
          return (
            <g key={id}>
              <circle cx={p.x} cy={p.y} r={root ? 6 : 3.5} fill={tone} />
              {root && <circle cx={p.x} cy={p.y} r={11} fill="none" stroke="var(--signal)" strokeWidth={0.8} />}
              <text x={p.x + (root ? 18 : 11)} y={p.y + 3.5} fontSize={root ? 12 : 10.5} fill={root ? "var(--ink)" : tone}
                    fontFamily={root ? "var(--font-display)" : "var(--font-mono)"} fontWeight={root ? 500 : 400}>
                {n.label.length > 26 ? n.label.slice(0, 25) + "…" : n.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function Key({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5 !text-faint">
      <span className="w-[6px] h-[6px] rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}
