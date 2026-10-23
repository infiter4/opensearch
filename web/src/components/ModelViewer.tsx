import { useEffect, useRef, useState } from "react";

/** Interactive 3D viewer for a doer-produced CAD artifact (.glb preferred, or .stl). Lazy-loads
 *  three.js (already bundled for the knowledge graph) so it costs nothing until opened. Drag to
 *  orbit, scroll to zoom. */
export function ModelViewer({ url }: { url: string }) {
  const host = useRef<HTMLDivElement>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    let cleanup = () => {};

    (async () => {
      try {
        const THREE = await import("three");
        const { OrbitControls } = await import("three/examples/jsm/controls/OrbitControls.js");
        const el = host.current;
        if (disposed || !el) return;

        const w = el.clientWidth || 640;
        const h = 440;
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x12191e);

        const camera = new THREE.PerspectiveCamera(45, w / h, 0.01, 100000);
        const renderer = new THREE.WebGLRenderer({ antialias: true });
        renderer.setSize(w, h);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        el.appendChild(renderer.domElement);

        scene.add(new THREE.HemisphereLight(0xffffff, 0x1a2128, 1.15));
        const key = new THREE.DirectionalLight(0xffffff, 1.25);
        key.position.set(4, 6, 5);
        scene.add(key);
        const rim = new THREE.DirectionalLight(0xe0912a, 0.35);
        rim.position.set(-5, 2, -4);
        scene.add(rim);

        const controls = new OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;

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
          const grid = new THREE.GridHelper(radius * 6, 20, 0x2a343d, 0x1c242b);
          grid.position.y = -size.y / 2;
          scene.add(grid);
        };

        const add = (obj: any) => { scene.add(obj); frame(obj); };
        const isStl = /\.stl(\?|$)/i.test(url);
        if (isStl) {
          const { STLLoader } = await import("three/examples/jsm/loaders/STLLoader.js");
          new STLLoader().load(url, (geo: any) => {
            if (disposed) return;
            geo.computeVertexNormals();
            const mesh = new THREE.Mesh(
              geo, new THREE.MeshStandardMaterial({ color: 0xcdd3da, metalness: 0.15, roughness: 0.55 }),
            );
            add(mesh);
          }, undefined, () => !disposed && setErr("could not load model"));
        } else {
          const { GLTFLoader } = await import("three/examples/jsm/loaders/GLTFLoader.js");
          new GLTFLoader().load(url, (g: any) => { if (!disposed) add(g.scene); },
            undefined, () => !disposed && setErr("could not load model"));
        }

        let raf = 0;
        const tick = () => { controls.update(); renderer.render(scene, camera); raf = requestAnimationFrame(tick); };
        tick();

        cleanup = () => {
          cancelAnimationFrame(raf);
          controls.dispose();
          renderer.dispose();
          if (renderer.domElement.parentNode === el) el.removeChild(renderer.domElement);
        };
      } catch {
        if (!disposed) setErr("3D viewer failed to load");
      }
    })();

    return () => { disposed = true; cleanup(); };
  }, [url]);

  return (
    <div>
      <div ref={host} className="w-full rule-t rule-b" style={{ height: 440 }} />
      <div className="label mt-1.5 !text-slate/50 flex items-center gap-3">
        <span>drag to orbit · scroll to zoom</span>
        <a href={url} download className="!text-amber hover:opacity-80">download ↓</a>
        {err && <span className="!text-amber">{err}</span>}
      </div>
    </div>
  );
}
