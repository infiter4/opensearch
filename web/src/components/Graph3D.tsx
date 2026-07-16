import { useEffect, useRef, useState } from "react";
import type { Exchange } from "../state/chat";

/* The ANSWER as a 3D knowledge graph.
 *
 * Not provenance. "question -> agent -> source" describes how the answer was made, which is a
 * story about us; this is the answer's own content — the plans, the prices, the limits, and the
 * relationships the answer states between them. Extracted server-side on first open (one model
 * call, cached on the session), laid out here.
 *
 * three.js is ~600KB, so the module is imported lazily on first expand and never rides in the
 * critical bundle. */

const TONE: Record<string, string> = {
  root: "#E0912A",     // the subject — the one amber thing
  entity: "#E7E1D4",   // plans, endpoints, products
  value: "#7FB2C4",    // prices, quotas, rates — the numbers
  concept: "#8A94A0",
};
const SIZE: Record<string, number> = { root: 30, entity: 12, value: 8, concept: 6 };

interface Concept { nodes: any[]; links: any[]; pending?: boolean }

export function Graph3D({ ex }: { ex: Exchange }) {
  const mount = useRef<HTMLDivElement>(null);
  const [data, setData] = useState<Concept | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!ex.queryId) { setErr("this conversation is too old to graph — ask again"); return; }
    let dead = false;
    setErr(null);
    fetch(`/api/concept?query_id=${ex.queryId}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => { if (!dead) setData(d); })
      .catch((e) => { if (!dead) setErr(String(e.message ?? e)); });
    return () => { dead = true; };
  }, [ex.queryId]);

  useEffect(() => {
    if (!data?.nodes?.length || !mount.current) return;
    let disposed = false;
    let graph: any;

    void Promise.all([import("3d-force-graph"), import("three")])
      .then(([mod, THREE]: any[]) => {
        if (disposed || !mount.current) return;
        const ForceGraph3D: any = mod.default;

        // A label per node. Without them a knowledge graph is just dots — the words ARE the data.
        const label = (n: any) => {
          const c = document.createElement("canvas");
          const font = 34;
          const probe = c.getContext("2d")!;
          probe.font = `600 ${font}px ui-monospace, monospace`;
          const text = String(n.label ?? "");
          c.width = probe.measureText(text).width + 20;
          c.height = font + 16;
          const g = c.getContext("2d")!;
          g.font = `600 ${font}px ui-monospace, monospace`;
          g.fillStyle = TONE[n.type] ?? "#E7E1D4";
          g.textBaseline = "middle";
          g.fillText(text, 10, c.height / 2);
          const tex = new THREE.CanvasTexture(c);
          tex.needsUpdate = true;
          const sprite = new THREE.Sprite(
            new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }),
          );
          const s = n.type === "root" ? 0.30 : 0.22;
          sprite.scale.set((c.width / c.height) * (font * s), font * s, 1);
          sprite.position.set(0, (SIZE[n.type] ?? 3) + 6, 0);
          return sprite;
        };

        graph = new ForceGraph3D(mount.current!)
          .width(mount.current!.clientWidth)
          .height(520)
          .backgroundColor("#00000000")
          .graphData(structuredClone(data))
          .nodeLabel((n: any) => n.label)
          .nodeColor((n: any) => TONE[n.type] ?? "#8A94A0")
          .nodeVal((n: any) => SIZE[n.type] ?? 3)
          .nodeOpacity(0.9)
          .nodeThreeObjectExtend(true)
          .nodeThreeObject(label)
          // Curvature is what makes it read as a web rather than a wiring diagram.
          .linkCurvature(0.25)
          .linkColor(() => "rgba(231,225,212,0.55)")
          .linkWidth(1.6)
          .linkOpacity(0.75)
          .linkLabel((l: any) => l.label || "")
          .linkDirectionalParticles(2)
          .linkDirectionalParticleWidth(2.2)
          .linkDirectionalParticleSpeed(0.005)
          .linkDirectionalParticleColor(() => "rgba(224,145,42,0.9)")
          .cooldownTicks(140)
          .onNodeClick((n: any) => {
            const dist = 90;
            const r = 1 + dist / Math.hypot(n.x || 1, n.y || 1, n.z || 1);
            graph.cameraPosition({ x: (n.x || 0) * r, y: (n.y || 0) * r, z: (n.z || 0) * r }, n, 900);
          });

        // Spread hard, then frame it. Left to itself the layout settles into a tight ball in the
        // middle of a 520px box and every label collides; the graph is only legible if the nodes
        // push each other apart AND the camera then pulls in to the bounding box that produces.
        graph.d3Force("charge")?.strength(-420);
        graph.d3Force("link")?.distance(95);
        graph.onEngineStop(() => graph.zoomToFit(900, 70));

        const onResize = () => graph?.width(mount.current?.clientWidth ?? 600);
        window.addEventListener("resize", onResize);
        graph.__cleanup = () => window.removeEventListener("resize", onResize);
      })
      .catch((e: any) => setErr(String(e?.message ?? e)));

    return () => {
      disposed = true;
      try { graph?.__cleanup?.(); graph?._destructor?.(); } catch { /* already gone */ }
    };
  }, [data]);

  if (err) return <div className="label !text-amber">could not build the graph: {err}</div>;
  if (!data) return <div className="label live-dot">reading the answer…</div>;
  if (data.pending) return <div className="label">the answer is not finished yet</div>;
  if (!data.nodes.length) return <div className="label">nothing graphable in this answer</div>;

  return (
    <div>
      <div className="label mb-2 flex flex-wrap items-center gap-x-4 gap-y-1">
        <span>{data.nodes.length} things · {data.links.length} relationships</span>
        <span className="flex-1" />
        <span className="text-[#E0912A]">● subject</span>
        <span className="text-paper/70">● entity</span>
        <span className="text-[#7FB2C4]">● value</span>
      </div>
      <div ref={mount} className="w-full" style={{ height: 520 }} />
      <div className="label !text-[9px] mt-1 text-slate/60">
        drag to rotate · scroll to zoom · click a node to fly to it
      </div>
    </div>
  );
}
