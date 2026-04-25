import { Suspense } from "react";
import { Canvas } from "@react-three/fiber";
import { Environment, Grid, PerspectiveCamera } from "@react-three/drei";
import * as THREE from "three";
import { useTwin } from "@/store/twin";
import { CameraRig } from "@/components/scene/CameraRig";
import { MachineModel } from "@/components/scene/MachineModel";

/**
 * SpatialScene — full-bleed React Three Fiber canvas that replaces the
 * Phase 2 SVG schematic. The HTML overlay (DashboardPanel, ARDataCard,
 * SpotlightChat, SimControls, etc.) is unchanged; this scene is sandwiched
 * underneath them with `position: absolute; inset: 0;`.
 *
 * Click semantics mirror Phase 2.8 exactly:
 *   • Click on a primitive   → setSelected(id), camera flies to focus.
 *   • Miss-click on background:
 *       - if zoomed in       → setSelected(null) (zoom out)
 *       - if in overview     → toggleDashboard() (tap-to-clear UI)
 */

const BG_COLOR = "#0f0f11";

export function SpatialScene() {
  const selectedId = useTwin((s) => s.selectedComponentId);
  const setSelected = useTwin((s) => s.selectComponent);
  const toggleDashboard = useTwin((s) => s.toggleDashboard);

  const onBackgroundClick = () => {
    if (selectedId) setSelected(null);
    else toggleDashboard();
  };

  return (
    <Canvas
      className="block h-full w-full min-h-0"
      // PCFSoft shadow map = soft penumbras + zero acne when paired with the
      // bias settings on the directional light below.
      shadows={{ type: THREE.PCFSoftShadowMap }}
      dpr={[1, 1.5]}
      gl={{ antialias: true, alpha: false, powerPreference: "default" }}
      onCreated={({ gl, scene }) => {
        scene.background = new THREE.Color(BG_COLOR);
        gl.toneMapping = THREE.ACESFilmicToneMapping;
        gl.toneMappingExposure = 1.05;
      }}
      // Fires only when a click misses every interactive mesh — wired in
      // SpatialScene up top to the dashboard tap-to-clear logic.
      onPointerMissed={(event) => {
        if (event.type === "click") onBackgroundClick();
      }}
    >
      {/*
        IMPORTANT: do NOT wrap the whole tree in a single <Suspense fallback={null}>.
        `Environment` (async HDRI) and drei's `Text` (font) can suspend; one boundary
        then delays *everything* (lights, floor, model) and reads as a black void.
        Keep sync geometry + lights outside async boundaries, async bits isolated.
      */}
      <PerspectiveCamera
        makeDefault
        position={[7.5, 3.6, 8.5]}
        fov={35}
        near={0.1}
        far={120}
        onUpdate={(cam) => cam.lookAt(-0.8, 1.7, 0)}
      />

      <Suspense fallback={null}>
        <CameraRig />
      </Suspense>
      <Lighting />
      <Floor />

      <Suspense fallback={null}>
        <MachineModel />
      </Suspense>

      <Suspense fallback={null}>
        <Environment preset="studio" />
      </Suspense>
      {/*
        ContactShadows can hard-fail on some Windows/ANGLE stacks and take the
        whole GL context with it — shadows come mostly from the key light; we
        can revisit with AccumulativeShadows or a post step if needed.
      */}
    </Canvas>
  );
}

/* ── Lights ─────────────────────────────────────────────────────────────── */

function Lighting() {
  return (
    <>
      <ambientLight intensity={0.20} />
      {/*
        Key light. Shadow tuning notes (Phase 3.7 fix for the flicker):
          • mapSize bumped 2048 → 4096 — a big chunk of the flicker on flat
            grey panels was just shadow-resolution aliasing.
          • Frustum tightened to ±7 around the model centre (~halved); each
            shadow texel covers ~14u/4096 = ~3.4mm at our scale.
          • bias more negative (−0.0006) + normalBias (0.04) — the standard
            recipe for killing shadow acne on PBR PCF soft shadows.
      */}
      <directionalLight
        position={[6, 10, 6]}
        intensity={1.45}
        color="#fff7ec"
        castShadow
        shadow-mapSize-width={4096}
        shadow-mapSize-height={4096}
        shadow-camera-near={1}
        shadow-camera-far={26}
        shadow-camera-left={-7}
        shadow-camera-right={7}
        shadow-camera-top={7}
        shadow-camera-bottom={-7}
        shadow-bias={-0.0006}
        shadow-normalBias={0.04}
      />
      {/* Cool fill from the opposite quadrant. No shadows — fill light
          shadows are usually noise more than information. */}
      <directionalLight position={[-6, 4, -3]} intensity={0.45} color="#9ec0ff" />
      {/* Subtle rim from behind so silhouettes pop against the dark bg. */}
      <directionalLight position={[0, 3, -7]} intensity={0.25} color="#ffe8ce" />
    </>
  );
}

/* ── Floor (very subtle architectural grid) ─────────────────────────────── */

function Floor() {
  return (
    <group position={[0, 0, 0]}>
      {/* Base receive-shadow plane — just barely lighter than the bg. */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <planeGeometry args={[60, 60]} />
        <meshStandardMaterial color="#101216" roughness={1} metalness={0} />
      </mesh>
      {/* Architectural grid that fades into the distance. */}
      <Grid
        args={[40, 40]}
        position={[0, 0.001, 0]}
        cellColor="#1c1e23"
        sectionColor="#2a2c33"
        cellSize={0.5}
        sectionSize={2.5}
        fadeDistance={22}
        fadeStrength={1.4}
        infiniteGrid
        followCamera={false}
      />
    </group>
  );
}
