import { useEffect, useRef } from "react";
import type { Exchange } from "../state/chat";

/* Interactive 3D provenance graph, deep mode only. Rendered lazily: three.js is ~600KB, so the
   module loads on first expand, never in the critical bundle. Node colours mirror the verdict
   vocabulary; the edges carry the worst verdict between an agent and a source, so a red strut in
   the structure IS a failed claim — same data as the ledger, different sense. */

const KIND_COLOR: Record<string, string> = {
  question: "#E7E1D4",
  agent: "#8A94A0",
  source: "#4A5560",
};
const VERDICT_COLOR: Record<string, string> = {
  supported: "#E7E1D4", weak: "#8A94A0", unsupported: "#E0912A",
  contradicted: "#E0912A", retracted: "#4A5560",
};

export function Graph3D({ ex }: { ex: Exchange }) {
  const mount = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ex.graph || !mount.current) return;
    let disposed = false;
    let graph: any;

    void import("3d-force-graph").then(({ default: ForceGraph3D }) => {
      if (disposed || !mount.current) return;
      graph = new (ForceGraph3D as any)(mount.current!)
        .width(mount.current!.clientWidth)
        .height(420)
        .backgroundColor("#00000000")
        .graphData(structuredClone(ex.graph!))
        .nodeLabel((n: any) => n.title ? `${n.label} — ${n.title}` : n.label)
        .nodeColor((n: any) => n.kind === "agent" && n.role === "red_team" ? "#E0912A" : KIND_COLOR[n.kind] ?? "#999")
        .nodeVal((n: any) => n.kind === "question" ? 10 : n.kind === "agent" ? 6 : 3)
        .linkColor((l: any) => VERDICT_COLOR[l.verdict] ?? "rgba(231,225,212,0.25)")
        .linkWidth((l: any) => (l.verdict === "contradicted" || l.verdict === "unsupported" ? 2.5 : 1))
        .linkOpacity(0.55)
        .onNodeClick((n: any) => { if (n.url) window.open(n.url, "_blank"); });
    });

    return () => {
      disposed = true;
      graph?._destructor?.();
    };
  }, [ex.graph]);

  if (!ex.graph) return null;
  return <div ref={mount} className="rounded overflow-hidden" style={{ minHeight: 420 }} />;
}
