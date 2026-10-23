import { useEffect, useRef, useState } from "react";
import { token, useTheme } from "../lib/theme";

/** Interactive 3D viewer for a doer-produced CAD artifact (.glb preferred, or .stl). Lazy-loads
 *  three.js (already bundled for the knowledge graph) so it costs nothing until opened. Drag to
 *  orbit, scroll to zoom. */
export function ModelViewer({ url }: { url: string }) {
  const host = useRef<HTMLDivElement>(null);
  const theme = useTheme();
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    // Teardown is registered the moment each resource exists. Assigning it only at the end left a
    // window — while the loader module was still downloading — where closing the viewer ran a
    // no-op cleanup, and the renderer it had already created kept a WebGL context and an
    // animation loop alive with nothing on screen.
    const undo: (() => void)[] = [];

    (async () => {
      try {
        const THREE = await import("three");
        const { OrbitControls } = await import("three/examples/jsm/controls/OrbitControls.js");
        const el = host.current;
        if (disposed || !el) return;

        const w = el.clientWidth || 640;
        const h = 440;
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(token("--raised") || "#eae6dc");

        const camera = new THREE.PerspectiveCamera(45, w / h, 0.01, 100000);
        const renderer = new THREE.WebGLRenderer({ antialias: true });
        renderer.setSize(w, h);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        el.appendChild(renderer.domElement);
        undo.push(() => {
          renderer.dispose();
          if (renderer.domElement.parentNode === el) el.removeChild(renderer.domElement);
        });

        scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 1.15));
        const key = new THREE.DirectionalLight(0xffffff, 1.25);
        key.position.set(4, 6, 5);
        scene.add(key);
        const rim = new THREE.DirectionalLight(new THREE.Color(token("--signal") || "#e2401c"), 0.35);
        rim.position.set(-5, 2, -4);
        scene.add(rim);

        const controls = new OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        undo.push(() => controls.dispose());

        const frame = (obj: any) => {
          const box = new THREE.Box3().setFromObject(obj);
          const size = box.getSize(new THREE.Vector3());
          const center = box.getCenter(new THREE.Vector3());
          obj.position.sub(center);                 // recenter at origin
          const radius = Math.max(size.x, size.y, size.z, 0.001);
          const dist = radius * 2.4;
          camera.position.set(dist * 0.8, dist * 0.6, dist);
          camera.near = radius / 100;
          camera.far = radius * 100;
          camera.updateProjectionMatrix();
          controls.target.set(0, 0, 0);
          controls.update();
          const line = new THREE.Color(token("--faint") || "#a29d90");
          const grid = new THREE.GridHelper(radius * 6, 20, line, line);
          (grid.material as any).opacity = 0.35;
          (grid.material as any).transparent = true;
          grid.position.y = -size.y / 2;
          scene.add(grid);
        };

        let raf = 0;
        const tick = () => { controls.update(); renderer.render(scene, camera); raf = requestAnimationFrame(tick); };
        tick();
        undo.push(() => cancelAnimationFrame(raf));

        const add = (obj: any) => { if (!disposed) { scene.add(obj); frame(obj); } };
        const fail = () => { if (!disposed) setErr("could not load model"); };
        if (/\.stl(\?|$)/i.test(url)) {
          const { STLLoader } = await import("three/examples/jsm/loaders/STLLoader.js");
          if (disposed) return;
          new STLLoader().load(url, (geo: any) => {
            geo.computeVertexNormals();
            add(new THREE.Mesh(
              geo, new THREE.MeshStandardMaterial({ color: 0xcdd3da, metalness: 0.15, roughness: 0.55 }),
            ));
          }, undefined, fail);
        } else {
          const { GLTFLoader } = await import("three/examples/jsm/loaders/GLTFLoader.js");
          if (disposed) return;
          new GLTFLoader().load(url, (g: any) => add(g.scene), undefined, fail);
        }
      } catch {
        if (!disposed) setErr("3D viewer failed to load");
      }
    })();

    return () => { disposed = true; for (const f of undo.reverse()) { try { f(); } catch { /* gone */ } } };
  }, [url, theme]);

  return (
    <div>
      <div ref={host} className="w-full rounded-[3px] overflow-hidden" style={{ height: 440 }} />
      <div className="label !text-faint mt-2 flex items-center gap-4">
        <span>drag to orbit · scroll to zoom</span>
        <a href={url} download>download ↓</a>
        {err && <span className="!text-signal">{err}</span>}
      </div>
    </div>
  );
}
