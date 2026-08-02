import React, { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useLoader, useThree } from "@react-three/fiber";
import { OrbitControls, useAnimations, useGLTF, useProgress } from "@react-three/drei";
import * as THREE from "three";
import { FBXLoader } from "three/examples/jsm/loaders/FBXLoader.js";

/** Bridge so the DOM lasso overlay (outside the Canvas) can project a part's
 * world centroid to screen pixels using the live camera. */
type Picker = { project: (name: string) => [number, number] | null; names: string[] };

/** Bad files (or wrong formats) degrade to a message, not a blank page. */
class ViewerBoundary extends React.Component<
  { children: React.ReactNode; resetKey: string },
  { err: Error | null }
> {
  state = { err: null as Error | null };
  static getDerivedStateFromError(err: Error) {
    return { err };
  }
  componentDidUpdate(prev: { resetKey: string }) {
    if (prev.resetKey !== (this.props as any).resetKey && this.state.err) this.setState({ err: null });
  }
  render() {
    if (this.state.err) {
      return (
        <div style={{ display: "grid", placeItems: "center", height: "100%", padding: 20, textAlign: "center", color: "var(--text-dim)", fontSize: 13 }}>
          <div>
            couldn't load this model in the viewer
            <div style={{ fontSize: 11, marginTop: 6, maxWidth: 420, wordBreak: "break-word" }}>
              {String(this.state.err.message || this.state.err).slice(0, 180)}
            </div>
            <div style={{ marginTop: 8 }}>download it, or branch a convert → GLTF to preview here</div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

/** DOM overlay shown while any model asset is streaming in (byte-accurate). */
function LoadingOverlay() {
  const { active, progress, item } = useProgress();
  const [done, setDone] = useState(false);
  useEffect(() => {
    if (active) setDone(false);
    else {
      const t = setTimeout(() => setDone(true), 250); // brief grace so 100% is visible
      return () => clearTimeout(t);
    }
  }, [active]);
  if (done && !active) return null;
  return (
    <div
      style={{
        position: "absolute", inset: 0, zIndex: 5, pointerEvents: "none",
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        gap: 10, background: "rgba(23,24,28,0.45)",
      }}
    >
      <div style={{ fontSize: 13, color: "var(--text-dim)" }}>
        loading model… {Math.round(progress)}%
      </div>
      <div style={{ width: 220, height: 6, borderRadius: 3, background: "var(--bg3)", overflow: "hidden" }}>
        <div
          style={{
            width: `${Math.max(3, progress)}%`, height: "100%",
            background: "var(--accent)", borderRadius: 3, transition: "width 0.2s",
          }}
        />
      </div>
      {item && (
        <div style={{ fontSize: 10, color: "var(--text-dim)", maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {item.split("/").pop()}
        </div>
      )}
    </div>
  );
}

interface InnerProps {
  object: THREE.Object3D;
  animations: THREE.AnimationClip[];
  wireframe: boolean;
  clip: string | null;
  bones: boolean;
  inPlace: boolean;
  partsMode: boolean;
  hiddenParts: Set<string>;
  selectMode: boolean;
  selected: Set<string>;
  pickerRef: React.MutableRefObject<Picker | null>;
  onHasBones: (has: boolean) => void;
  onParts: (parts: string[]) => void;
  onClips: (clips: string[]) => void;
}

function GltfModel({ url, ...rest }: { url: string } & Omit<InnerProps, "object" | "animations">) {
  const gltf = useGLTF(url);
  return <ModelInner object={gltf.scene} animations={gltf.animations} {...rest} />;
}

function FbxModel({ url, ...rest }: { url: string } & Omit<InnerProps, "object" | "animations">) {
  const fbx = useLoader(FBXLoader, url);
  return <ModelInner object={fbx} animations={fbx.animations ?? []} {...rest} />;
}

function ModelInner({
  object,
  animations,
  wireframe,
  clip,
  bones,
  inPlace,
  partsMode,
  hiddenParts,
  selectMode,
  selected,
  pickerRef,
  onHasBones,
  onParts,
  onClips,
}: InnerProps) {
  const { actions } = useAnimations(animations, object);
  const { camera, gl } = useThree();
  useEffect(() => {
    onClips(animations.map((a) => a.name));
  }, [animations, onClips]);
  const groupRef = useRef<THREE.Group>(null);

  useEffect(() => {
    Object.values(actions).forEach((a) => a?.stop());
    if (clip && actions[clip]) actions[clip]!.reset().play();
  }, [clip, actions]);

  // skinned meshes: pose can leave the bind-pose bounds -> never frustum-cull
  useEffect(() => {
    object.traverse((o: any) => {
      if (o.isSkinnedMesh) o.frustumCulled = false;
    });
  }, [object]);

  const rootBone = useMemo(() => {
    let b: THREE.Bone | null = null;
    object.traverse((o: any) => {
      if (!b && o.isSkinnedMesh && o.skeleton?.bones?.length) b = o.skeleton.bones[0];
    });
    return b;
  }, [object]);

  // named parts (segmentation output = one named mesh per part)
  const partMeshes = useMemo(() => {
    const map = new Map<string, THREE.Mesh[]>();
    object.traverse((o: any) => {
      if (o.isMesh) {
        const nm = o.name || o.parent?.name || `part_${map.size}`;
        if (!map.has(nm)) map.set(nm, []);
        map.get(nm)!.push(o);
      }
    });
    return map;
  }, [object]);

  useEffect(() => {
    onParts(partMeshes.size > 1 ? [...partMeshes.keys()] : []);
  }, [partMeshes, onParts]);

  // color-by-part override (originals restored on toggle-off). Selected parts
  // are forced bright + emissive so a lasso pick reads clearly against the hues.
  useEffect(() => {
    const names = [...partMeshes.keys()];
    names.forEach((nm, i) => {
      const sel = selected.has(nm);
      for (const m of partMeshes.get(nm)!) {
        if (partsMode) {
          if (!m.userData.__origMat) m.userData.__origMat = m.material;
          m.material = new THREE.MeshStandardMaterial({
            color: sel ? new THREE.Color(0xffffff) : new THREE.Color().setHSL((i * 0.618) % 1, 0.65, 0.55),
            emissive: sel ? new THREE.Color(0x3355ff) : new THREE.Color(0x000000),
            emissiveIntensity: sel ? 0.6 : 0,
            roughness: 0.7, metalness: 0.05,
          });
        } else if (m.userData.__origMat) {
          m.material = m.userData.__origMat;
          delete m.userData.__origMat;
        }
      }
    });
  }, [partsMode, partMeshes, selected]);

  // part centroids in world space (model is static; only the camera moves while
  // selecting) → recomputed when parts change or select mode turns on
  const centroidsRef = useRef<Map<string, THREE.Vector3>>(new Map());
  useEffect(() => {
    if (!selectMode) return;
    const g = groupRef.current;
    if (!g) return;
    g.updateWorldMatrix(true, true);
    const m = new Map<string, THREE.Vector3>();
    partMeshes.forEach((ms, nm) => {
      const box = new THREE.Box3();
      ms.forEach((mesh) => box.expandByObject(mesh));
      if (!box.isEmpty()) m.set(nm, box.getCenter(new THREE.Vector3()));
    });
    centroidsRef.current = m;
  }, [selectMode, partMeshes]);

  // expose a live projector to the DOM overlay (camera is mutated in place by
  // OrbitControls, so reading it at pointer-up gives the current view)
  useEffect(() => {
    pickerRef.current = {
      names: [...partMeshes.keys()],
      project: (nm) => {
        const c = centroidsRef.current.get(nm);
        if (!c) return null;
        const v = c.clone().project(camera);
        const el = gl.domElement;
        return [(v.x * 0.5 + 0.5) * el.clientWidth, (-v.y * 0.5 + 0.5) * el.clientHeight];
      },
    };
    return () => { pickerRef.current = null; };
  }, [pickerRef, camera, gl, partMeshes]);

  useEffect(() => {
    partMeshes.forEach((ms, nm) => ms.forEach((m) => { m.visible = !hiddenParts.has(nm); }));
  }, [hiddenParts, partMeshes]);

  // skeleton overlay: single helper over the whole scene, rendered OUTSIDE the
  // normalization group (it tracks bone world positions itself — parenting it
  // inside the scaled group would double-transform it)
  const helper = useMemo(() => {
    let skinned = false;
    object.traverse((o: any) => {
      if (o.isSkinnedMesh && o.skeleton?.bones?.length) skinned = true;
    });
    if (!skinned) return null;
    const h = new THREE.SkeletonHelper(object);
    (h.material as THREE.LineBasicMaterial).depthTest = false;
    h.renderOrder = 999;
    return h;
  }, [object]);

  useEffect(() => onHasBones(!!helper), [helper, onHasBones]);

  useEffect(() => {
    object.traverse((o: any) => {
      if (o.isMesh && o.material) {
        const mats = Array.isArray(o.material) ? o.material : [o.material];
        mats.forEach((m: any) => (m.wireframe = wireframe));
      }
    });
  }, [wireframe, object]);

  // auto-center + scale to unit-ish size
  const { position, scale } = useMemo(() => {
    const box = new THREE.Box3().setFromObject(object);
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    const s = sphere.radius > 0 ? 1.6 / sphere.radius : 1;
    return {
      scale: s,
      position: [-sphere.center.x * s, -sphere.center.y * s, -sphere.center.z * s] as [number, number, number],
    };
  }, [object]);

  // root-motion compensation: pin the root bone's XZ to the viewer origin so
  // clips that translate the root (e.g. Tripo preset:walk) play "in place".
  // No anchor to capture (transient first-frame poses made anchors unreliable);
  // bone position is read in group-local space, invariant to the group transform.
  useFrame(() => {
    const g = groupRef.current;
    if (!g) return;
    if (!clip || !inPlace || !rootBone) {
      g.position.set(position[0], position[1], position[2]);
      return;
    }
    const p = (rootBone as THREE.Bone).getWorldPosition(new THREE.Vector3());
    g.worldToLocal(p);
    g.position.set(-p.x * scale, position[1], -p.z * scale); // keep vertical bob
  });

  return (
    <>
      <group ref={groupRef} position={position} scale={scale}>
        <primitive object={object} />
      </group>
      {bones && helper && <primitive object={helper} />}
    </>
  );
}

function pointInPolygon(pt: [number, number], poly: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > pt[1]) !== (yj > pt[1]) &&
        pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** onFuse: merge the given part names into one — creates a fuse child node.
 * When present (and the model has >1 part) the viewer offers lasso part-selection. */
export function ModelViewer({ url, format = "glb", onFuse }: {
  url: string; format?: string;
  onFuse?: (parts: string[]) => Promise<void>;
}) {
  const [wireframe, setWireframe] = useState(false);
  const [clips, setClips] = useState<string[]>([]);
  const [clip, setClip] = useState<string | null>(null);
  const [bones, setBones] = useState(false);
  const [hasBones, setHasBones] = useState(false);
  const [inPlace, setInPlace] = useState(true);
  const [partsMode, setPartsMode] = useState(false);
  const [parts, setParts] = useState<string[]>([]);
  const [hiddenParts, setHiddenParts] = useState<Set<string>>(new Set());
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [lasso, setLasso] = useState<[number, number][]>([]);
  const [fusing, setFusing] = useState(false);
  const pickerRef = useRef<Picker | null>(null);
  const draggingRef = useRef(false);

  const canFuse = !!onFuse && parts.length > 1;

  function enterSelect() {
    setSelectMode(true);
    setPartsMode(true);       // selection only makes sense over per-part coloring
  }
  function exitSelect() {
    setSelectMode(false);
    setSelected(new Set());
    setLasso([]);
  }

  function commitLasso(poly: [number, number][], additive: boolean) {
    const picker = pickerRef.current;
    if (!picker) return;
    const hit = new Set<string>();
    for (const nm of picker.names) {
      const p = picker.project(nm);
      if (p && pointInPolygon(p, poly)) hit.add(nm);
    }
    setSelected((prev) => {
      const next = additive ? new Set(prev) : new Set<string>();
      hit.forEach((h) => (next.has(h) ? next.delete(h) : next.add(h)));
      return next;
    });
  }

  const inner = {
    wireframe, clip, bones, inPlace, partsMode, hiddenParts, selectMode, selected, pickerRef,
    onHasBones: setHasBones, onParts: setParts, onClips: setClips,
  };

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <ViewerBoundary resetKey={url}>
      <LoadingOverlay />
      <Canvas camera={{ position: [2.2, 1.4, 2.6], fov: 40 }} gl={{ antialias: true }}>
        <color attach="background" args={["#232529"]} />
        <hemisphereLight args={[0xffffff, 0x445566, 1.1]} />
        <directionalLight position={[3, 5, 4]} intensity={2.0} />
        <directionalLight position={[-4, 2, -2]} intensity={0.8} />
        <directionalLight position={[0, 4, -5]} intensity={0.6} />
        <Suspense fallback={null}>
          {format === "fbx" ? (
            <FbxModel url={url} {...inner} />
          ) : (
            <GltfModel url={url} {...inner} />
          )}
        </Suspense>
        <OrbitControls makeDefault enableDamping enabled={!selectMode} />
        <gridHelper args={[10, 20, "#3a3d45", "#2c2e34"]} position={[0, -1.05, 0]} />
      </Canvas>

      {/* lasso overlay — captures drags while selecting; orbit is paused. */}
      {selectMode && (
        <svg
          width="100%" height="100%"
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%",
                   zIndex: 7, cursor: "crosshair", touchAction: "none" }}
          onPointerDown={(e) => {
            (e.target as Element).setPointerCapture?.(e.pointerId);
            const r = e.currentTarget.getBoundingClientRect();
            draggingRef.current = true;
            setLasso([[e.clientX - r.left, e.clientY - r.top]]);
          }}
          onPointerMove={(e) => {
            if (!draggingRef.current) return;
            const r = e.currentTarget.getBoundingClientRect();
            const pt: [number, number] = [e.clientX - r.left, e.clientY - r.top];
            setLasso((prev) => {
              const last = prev[prev.length - 1];
              if (last && Math.hypot(pt[0] - last[0], pt[1] - last[1]) < 4) return prev;
              return [...prev, pt];
            });
          }}
          onPointerUp={(e) => {
            draggingRef.current = false;
            setLasso((poly) => {
              if (poly.length >= 3) commitLasso(poly, true);
              return [];
            });
          }}
        >
          {lasso.length > 1 && (
            <polygon
              points={lasso.map((p) => p.join(",")).join(" ")}
              fill="rgba(60,110,255,0.12)" stroke="#5a8cff" strokeWidth={1.5}
              strokeDasharray="4 3"
            />
          )}
        </svg>
      )}

      {partsMode && parts.length > 1 && (
        <div
          style={{
            position: "absolute", top: 8, right: 8, zIndex: 8, maxHeight: "85%",
            overflowY: "auto", background: "rgba(23,24,28,0.85)", borderRadius: 8,
            padding: "8px 10px", fontSize: 12, display: "flex", flexDirection: "column", gap: 4,
          }}
        >
          {parts.map((p, i) => (
            <label key={p} style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer",
                                    opacity: hiddenParts.has(p) ? 0.4 : 1,
                                    outline: selected.has(p) ? "1px solid #5a8cff" : "none",
                                    borderRadius: 3, padding: "0 2px" }}>
              <input
                type="checkbox"
                checked={selectMode ? selected.has(p) : !hiddenParts.has(p)}
                onChange={() =>
                  selectMode
                    ? setSelected((prev) => {
                        const next = new Set(prev);
                        next.has(p) ? next.delete(p) : next.add(p);
                        return next;
                      })
                    : setHiddenParts((prev) => {
                        const next = new Set(prev);
                        next.has(p) ? next.delete(p) : next.add(p);
                        return next;
                      })
                }
              />
              <span style={{ width: 10, height: 10, borderRadius: 3, flexShrink: 0,
                             background: `hsl(${((i * 0.618) % 1) * 360}deg 65% 55%)` }} />
              {p}
            </label>
          ))}
        </div>
      )}
      <div style={{ position: "absolute", top: 8, left: 8, display: "flex", gap: 6, zIndex: 8, flexWrap: "wrap" }}>
        <button onClick={() => setWireframe((w) => !w)}>{wireframe ? "shaded" : "wireframe"}</button>
        {hasBones && (
          <button onClick={() => setBones((b) => !b)}>{bones ? "hide bones" : "show bones"}</button>
        )}
        {parts.length > 1 && (
          <button onClick={() => setPartsMode((v) => !v)}>{partsMode ? "materials" : `parts (${parts.length})`}</button>
        )}
        {canFuse && !selectMode && (
          <button onClick={enterSelect} title="lasso-select parts to merge">⧉ select parts</button>
        )}
        {selectMode && (
          <>
            <span style={{ alignSelf: "center", fontSize: 12, color: "var(--text-dim)", padding: "0 4px" }}>
              {selected.size} selected
            </span>
            <button
              disabled={selected.size < 2 || fusing}
              onClick={async () => {
                if (!onFuse || selected.size < 2) return;
                setFusing(true);
                try { await onFuse([...selected]); exitSelect(); }
                finally { setFusing(false); }
              }}
            >
              {fusing ? "fusing…" : `⛓ fuse ${selected.size}`}
            </button>
            {selected.size > 0 && <button onClick={() => setSelected(new Set())}>clear</button>}
            <button onClick={exitSelect}>done</button>
          </>
        )}
        {clips.length > 0 && (
          <>
            <select value={clip ?? ""} onChange={(e) => setClip(e.target.value || null)}>
              <option value="">no animation</option>
              {clips.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            {clip && (
              <button onClick={() => setInPlace((v) => !v)} title="cancel root motion during playback">
                {inPlace ? "roaming" : "in place"}
              </button>
            )}
          </>
        )}
      </div>
      {selectMode && (
        <div style={{ position: "absolute", bottom: 8, left: 8, zIndex: 8, fontSize: 11,
                      color: "var(--text-dim)", background: "rgba(23,24,28,0.7)", padding: "3px 8px",
                      borderRadius: 6, pointerEvents: "none" }}>
          drag to lasso parts · tick legend to fine-tune · orbit paused while selecting
        </div>
      )}
      </ViewerBoundary>
    </div>
  );
}

