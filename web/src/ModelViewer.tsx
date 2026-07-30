import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls, useAnimations, useGLTF, useProgress } from "@react-three/drei";
import * as THREE from "three";

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

function Model({
  url,
  wireframe,
  clip,
  bones,
  inPlace,
  onHasBones,
}: {
  url: string;
  wireframe: boolean;
  clip: string | null;
  bones: boolean;
  inPlace: boolean;
  onHasBones: (has: boolean) => void;
}) {
  const gltf = useGLTF(url);
  const { actions } = useAnimations(gltf.animations, gltf.scene);
  const groupRef = useRef<THREE.Group>(null);

  useEffect(() => {
    Object.values(actions).forEach((a) => a?.stop());
    if (clip && actions[clip]) actions[clip]!.reset().play();
  }, [clip, actions]);

  // skinned meshes: pose can leave the bind-pose bounds -> never frustum-cull
  useEffect(() => {
    gltf.scene.traverse((o: any) => {
      if (o.isSkinnedMesh) o.frustumCulled = false;
    });
  }, [gltf.scene]);

  const rootBone = useMemo(() => {
    let b: THREE.Bone | null = null;
    gltf.scene.traverse((o: any) => {
      if (!b && o.isSkinnedMesh && o.skeleton?.bones?.length) b = o.skeleton.bones[0];
    });
    return b;
  }, [gltf.scene]);

  // skeleton overlay: single helper over the whole scene, rendered OUTSIDE the
  // normalization group (it tracks bone world positions itself — parenting it
  // inside the scaled group would double-transform it)
  const helper = useMemo(() => {
    let skinned = false;
    gltf.scene.traverse((o: any) => {
      if (o.isSkinnedMesh && o.skeleton?.bones?.length) skinned = true;
    });
    if (!skinned) return null;
    const h = new THREE.SkeletonHelper(gltf.scene);
    (h.material as THREE.LineBasicMaterial).depthTest = false;
    h.renderOrder = 999;
    return h;
  }, [gltf.scene]);

  useEffect(() => onHasBones(!!helper), [helper, onHasBones]);

  useEffect(() => {
    gltf.scene.traverse((o: any) => {
      if (o.isMesh && o.material) {
        const mats = Array.isArray(o.material) ? o.material : [o.material];
        mats.forEach((m: any) => (m.wireframe = wireframe));
      }
    });
  }, [wireframe, gltf.scene]);

  // auto-center + scale to unit-ish size
  const { position, scale } = useMemo(() => {
    const box = new THREE.Box3().setFromObject(gltf.scene);
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    const s = sphere.radius > 0 ? 1.6 / sphere.radius : 1;
    return {
      scale: s,
      position: [-sphere.center.x * s, -sphere.center.y * s, -sphere.center.z * s] as [number, number, number],
    };
  }, [gltf.scene]);

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
        <primitive object={gltf.scene} />
      </group>
      {bones && helper && <primitive object={helper} />}
    </>
  );
}

export function ModelViewer({ url }: { url: string }) {
  const [wireframe, setWireframe] = useState(false);
  const [clips, setClips] = useState<string[]>([]);
  const [clip, setClip] = useState<string | null>(null);
  const [bones, setBones] = useState(false);
  const [hasBones, setHasBones] = useState(false);
  const [inPlace, setInPlace] = useState(true);

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <LoadingOverlay />
      <Canvas camera={{ position: [2.2, 1.4, 2.6], fov: 40 }} gl={{ antialias: true }}>
        <color attach="background" args={["#232529"]} />
        <hemisphereLight args={[0xffffff, 0x445566, 1.1]} />
        <directionalLight position={[3, 5, 4]} intensity={2.0} />
        <directionalLight position={[-4, 2, -2]} intensity={0.8} />
        <directionalLight position={[0, 4, -5]} intensity={0.6} />
        <Suspense fallback={null}>
          <ClipProbe url={url} onClips={setClips} />
          <Model url={url} wireframe={wireframe} clip={clip} bones={bones} inPlace={inPlace} onHasBones={setHasBones} />
        </Suspense>
        <OrbitControls makeDefault enableDamping />
        <gridHelper args={[10, 20, "#3a3d45", "#2c2e34"]} position={[0, -1.05, 0]} />
      </Canvas>
      <div style={{ position: "absolute", top: 8, left: 8, display: "flex", gap: 6 }}>
        <button onClick={() => setWireframe((w) => !w)}>{wireframe ? "shaded" : "wireframe"}</button>
        {hasBones && (
          <button onClick={() => setBones((b) => !b)}>{bones ? "hide bones" : "show bones"}</button>
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
    </div>
  );
}

function ClipProbe({ url, onClips }: { url: string; onClips: (c: string[]) => void }) {
  const gltf = useGLTF(url);
  useEffect(() => {
    onClips(gltf.animations.map((a) => a.name));
  }, [gltf.animations, onClips]);
  return null;
}
