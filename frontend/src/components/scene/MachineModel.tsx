import { useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ReactElement } from "react";
import { useFrame, type ThreeEvent } from "@react-three/fiber";
import { Outlines, RoundedBox, useCursor, useTexture } from "@react-three/drei";
import {
  Color,
  SRGBColorSpace,
  type Group,
  type LineBasicMaterial,
  type LineSegments,
  type Material,
  type Mesh,
  Mesh as MeshValue,
  type MeshPhysicalMaterial,
  type MeshStandardMaterial,
  type PointLight,
  type RectAreaLight,
} from "three";
// RectAreaLight requires its uniforms LUT initialised once at module load —
// this is a one-time side effect; importing twice is a no-op.
import { RectAreaLightUniformsLib } from "three/examples/jsm/lights/RectAreaLightUniformsLib.js";
RectAreaLightUniformsLib.init();
import { damp, damp3 } from "maath/easing";
import { useTwin } from "@/store/twin";
import type { ComponentId, OperationalStatus, SystemSnapshot } from "@/types/telemetry";
import {
  HOOD_SMART_LIFT_DELTA,
  hoodSmartLiftMeters,
  isHoodSmartLiftTarget,
} from "@/components/scene/hoodSmartLift";

/**
 * MachineModel — high-fidelity HP Metal Jet S100 reproduction.
 *
 *   ┌──────┐ ┌─────────────────────────────────┐
 *   │      │ │     Charcoal hood + exhaust     │
 *   │ Tower│ │                                 │
 *   │ ░ stk│ │ ┌── HOLLOW CAVITY ─────────┐    │
 *   │ ░ scr│ │ │ • Build chamber           │ ◄── lit from inside
 *   │ ░ rfd│ │ │ • Printhead              │    │
 *   │ ░ btn│ │ │ • Recoater bridge        │    │
 *   │      │ │ ╞════ Hinged door ═════════╡    │ ──────────── horizontal cyan
 *   │      │ │ │   (HP logo, swings open) │    │              light bar (right)
 *   └──────┘ └─────────────────────────────────┘
 *
 * The chassis is now a SHELL — bottom + left + right + back + hood — with the
 * front open and covered by the hinged main door. Internals live inside the
 * cavity and are revealed when the door swings open + the shell fades to
 * `SHELL_DIM_OPACITY`. A `SanctumLight` lifts its intensity in lock-step.
 */

/* ── Shared timing ──────────────────────────────────────────────────────── */

const POSITION_SMOOTH = 0.40;
const SCALE_SMOOTH = 0.18;
const DOOR_SMOOTH = 0.55;
const SHELL_SMOOTH = 0.45;
const PULSE_SPEED = 2.4;

const DOOR_OPEN_ANGLE = -1.95;
const SHELL_DIM_OPACITY = 0.2;

/* ── Mock "Execute Print" animation constants ───────────────────────────── */

/**
 * Z-axis travel of the recoater roller during the spreading animation (m).
 * Stays well inside the powder-bed half-depth (1.32 m / 2 = 0.66 m) so the
 * roller's body — itself ~1.55 m long, sitting on top of a 1.6 m chamber —
 * never punches through the chassis side walls during the sweep.
 */
const PRINT_RECOATER_TRAVEL = 0.32;
/** Period of one full back-and-forth sweep (s). */
const PRINT_RECOATER_PERIOD = 1.4;
/** Smooth ease-in/out scaler so the recoater doesn't snap to its travel envelope. */
const PRINT_ENVELOPE_SMOOTH = 0.20;
/** Peak intensity of the warm chamber point light during fusing. */
const PRINT_LIGHT_PEAK = 38;
/** Period of the laser/fusing pulse (s). Slightly faster than the sweep so they read as independent systems. */
const PRINT_LIGHT_PERIOD = 0.75;

/* ── Status palette ─────────────────────────────────────────────────────── */

function tintFor(status: OperationalStatus): string | null {
  if (status === "FAILED" || status === "CRITICAL") return "#ff8269";
  if (status === "DEGRADED") return "#f5c382";
  return null;
}

const STATUS_ORDER: OperationalStatus[] = ["FUNCTIONAL", "DEGRADED", "CRITICAL", "FAILED"];

function worstStatus(snap: SystemSnapshot, ids: ComponentId[]): OperationalStatus {
  let worst: OperationalStatus = "FUNCTIONAL";
  for (const c of snap.components) {
    if (!ids.includes(c.id)) continue;
    if (STATUS_ORDER.indexOf(c.status) > STATUS_ORDER.indexOf(worst)) worst = c.status;
  }
  return worst;
}

/* ── Material palette (matches the reference photo's tonal range) ───────── */

const MATTE_BLACK = "#1a1a1a";       // control tower
const PANEL_LIGHT = "#e0e0e0";       // lower industrial grey
const PANEL_LIGHT_DK = "#cdcdcf";    // back wall — slightly darker for depth
const HOOD_CHARCOAL = "#2a2b2e";     // upper hood
const ACCENT_CYAN = "#00e5ff";       // signature HP light bar
const ACCENT_CYAN_SOFT = "#3ea3d6";  // softer cyan for door handles
const ACCENT_GLOW = new Color("#7ec3ff"); // matches CSS --color-accent
/** "Clinical" selection glow (Apple-tier). */
const SELECTION_EMISSIVE = new Color("#e0f7fa");
const SELECTION_EMISSIVE_INT = 0.5;
const SELECTION_SMOOTH = 0.22;
const OUTLINE_SMOOTH = 0.24;
const HOOD_LIFT_SMOOTH = 0.48; // heavy industrial reveal
/**
 * When the shell is faded open (opacity < this), the chassis no longer
 * blocks raycasts — clicks reach internal parts so the first hit isn't a
 * semi-transparent wall (fixes accidental zoom-out / door jank).
 */
const CHASSIS_RAY_PASSTHROUGH_BELOW = 0.75;

function noRaycast() {
  /* three.js: empty raycast = no hits */
}

/** Clicks on passive chassis are swallowed so they do not fire canvas-level / sibling logic. */
function blockChassis(e: ThreeEvent<MouseEvent>) {
  e.stopPropagation();
}

/* ── FadeGroup — auto-applies opacity to every material in its subtree ──── */

interface FadeableMaterial extends Material {
  opacity: number;
  transparent: boolean;
  depthWrite: boolean;
}

/**
 * Walks the subtree once per frame and writes the latest opacity from
 * `opacityRef` into every material it finds. Avoids the bookkeeping mess
 * of registering material refs one-by-one when we have many small panels.
 *
 * Place it around the chassis content; keep `LightBar`, `Feet` and
 * `SanctumLight` OUTSIDE so they remain at full intensity always.
 */
function FadeGroup({
  opacityRef,
  children,
}: {
  opacityRef: React.MutableRefObject<number>;
  children: React.ReactNode;
}) {
  const groupRef = useRef<Group>(null);

  useFrame(() => {
    const g = groupRef.current;
    if (!g) return;
    const target = opacityRef.current;
    const transparent = target < 0.999;
    const depthWrite = target > 0.5;
    g.traverse((obj) => {
      const mesh = obj as Mesh;
      if (!mesh.isMesh) return;
      const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      for (const raw of mats) {
        if (!raw) continue;
        const m = raw as FadeableMaterial;
        if (typeof m.opacity !== "number") continue;
        m.opacity = target;
        m.transparent = transparent;
        m.depthWrite = depthWrite;
      }
      // Pass-thru: dimmed multi-layer shell must not win the ray over internals.
      const pass = target < CHASSIS_RAY_PASSTHROUGH_BELOW;
      if (pass) {
        if (!mesh.userData._twinRayOff) {
          mesh.userData._twinOrigRaycast = mesh.raycast;
          mesh.raycast = noRaycast;
          mesh.userData._twinRayOff = true;
        }
      } else if (mesh.userData._twinRayOff) {
        const orig = mesh.userData._twinOrigRaycast as Mesh["raycast"] | undefined;
        mesh.raycast = orig ?? MeshValue.prototype.raycast;
        delete mesh.userData._twinOrigRaycast;
        mesh.userData._twinRayOff = false;
      }
    });
  });

  return <group ref={groupRef}>{children}</group>;
}

/* ── Hover-pulse hook (subtle accent breath on exterior parts) ──────────── */

function useHoverPulse(min: number, max: number) {
  const matRef = useRef<MeshStandardMaterial | MeshPhysicalMaterial | null>(null);
  const hoveredRef = useRef(false);
  const setHovered = (v: boolean) => { hoveredRef.current = v; };

  useFrame((state, delta) => {
    const m = matRef.current;
    if (!m) return;
    if (hoveredRef.current) {
      const mid = (min + max) / 2;
      const amp = (max - min) / 2;
      m.emissiveIntensity = mid + Math.sin(state.clock.elapsedTime * PULSE_SPEED) * amp;
      m.emissive.lerp(ACCENT_GLOW, 0.18);
    } else {
      damp(m, "emissiveIntensity", min, 0.25, delta);
      m.emissive.lerp(new Color("#000000"), 0.12);
    }
  });

  return { matRef, setHovered };
}

/* ── Control Tower (left) ───────────────────────────────────────────────── */

function ControlTower() {
  const screenMatRef = useRef<MeshStandardMaterial>(null);
  // Phase 3.9 fix: the Control Cabinet is NOT a tracked telemetry component.
  // It only houses the touchscreen + e-stop + compute. Previously clicking it
  // wrongly zoomed into the Build Unit Heater. We now treat it as a passive
  // landmark — hover-pulse only, no click handler, no pointer cursor.
  const { matRef: bodyMatRef, setHovered } = useHoverPulse(0.02, 0.10);

  useFrame((state) => {
    const m = screenMatRef.current;
    if (m) {
      const t = state.clock.elapsedTime;
      m.emissiveIntensity = 0.85 + Math.sin(t * 0.6) * 0.05;
    }
  });

  return (
    <group position={[-3.7, 0, 0]} onClick={blockChassis}>
      {/* Body (matte black) — passive; clicks swallowed at cabinet level. */}
      <group
        onPointerOver={(e) => { e.stopPropagation(); setHovered(true); }}
        onPointerOut={() => setHovered(false)}
      >
        <RoundedBox args={[1.0, 4.6, 1.6]} radius={0.04} smoothness={4}
          position={[0, 2.3, 0]} castShadow receiveShadow>
          <meshPhysicalMaterial
            ref={bodyMatRef}
            color={MATTE_BLACK}
            roughness={0.85}
            metalness={0.06}
            clearcoat={0.12}
            clearcoatRoughness={0.7}
          />
        </RoundedBox>
      </group>

      {/* Touchscreen (slightly inset emissive panel) */}
      <RoundedBox args={[0.62, 0.5, 0.02]} radius={0.02} smoothness={2}
        position={[0, 3.6, 0.815]}>
        <meshStandardMaterial color="#0d0e10" roughness={0.6} metalness={0.3} />
      </RoundedBox>
      <RoundedBox args={[0.55, 0.42, 0.04]} radius={0.015} smoothness={3}
        position={[0, 3.6, 0.83]}>
        <meshStandardMaterial
          ref={screenMatRef}
          color="#4ea1d1"
          emissive="#5db8e8"
          emissiveIntensity={0.85}
          roughness={0.25}
          metalness={0.4}
        />
      </RoundedBox>

      {/* HP card-reader / RFID */}
      <RoundedBox args={[0.34, 0.18, 0.04]} radius={0.015} smoothness={2}
        position={[0, 3.0, 0.82]}>
        <meshStandardMaterial color="#0d0e10" roughness={0.5} metalness={0.45} />
      </RoundedBox>
      <mesh position={[-0.10, 3.0, 0.842]}>
        <circleGeometry args={[0.018, 16]} />
        <meshStandardMaterial color="#222" emissive="#7ec3ff" emissiveIntensity={0.25} />
      </mesh>

      {/* E-stop (red on yellow housing) */}
      <RoundedBox args={[0.32, 0.32, 0.05]} radius={0.04} smoothness={3}
        position={[0, 2.28, 0.82]} castShadow>
        <meshStandardMaterial color="#d8c43a" roughness={0.5} metalness={0.1} />
      </RoundedBox>
      <mesh position={[0, 2.28, 0.86]} castShadow>
        <cylinderGeometry args={[0.10, 0.10, 0.06, 24]} />
        <meshStandardMaterial color="#c12a26" roughness={0.45} metalness={0.15} />
      </mesh>

      {/* Status signal stack on top */}
      <group position={[0, 4.8, 0]}>
        <mesh position={[0, 0.4, 0]} castShadow>
          <cylinderGeometry args={[0.04, 0.04, 0.8, 12]} />
          <meshStandardMaterial color="#222" roughness={0.6} metalness={0.5} />
        </mesh>
        {[
          { color: "#5fd185", emissive: "#5fd185", y: 0.95, live: true },
          { color: "#f0c14b", emissive: "#f0c14b", y: 1.18, live: false },
          { color: "#e4555a", emissive: "#e4555a", y: 1.41, live: false },
          { color: "#5fa3e4", emissive: "#5fa3e4", y: 1.64, live: false },
        ].map((seg, i) => (
          <mesh key={i} position={[0, seg.y, 0]} castShadow>
            <cylinderGeometry args={[0.13, 0.13, 0.20, 24]} />
            <meshStandardMaterial
              color={seg.color}
              emissive={seg.emissive}
              emissiveIntensity={seg.live ? 1.4 : 0.45}
              roughness={0.55}
              metalness={0.1}
              transparent
              opacity={0.92}
            />
          </mesh>
        ))}
      </group>

      {/* Foot */}
      <mesh position={[0, 0, 0]} castShadow>
        <cylinderGeometry args={[0.08, 0.10, 0.18, 16]} />
        <meshStandardMaterial color="#3a3c40" roughness={0.4} metalness={0.6} />
      </mesh>
    </group>
  );
}

/* ── Hollow main body — 5 walls + hood, front open for the hinged door ─── */

const BODY = {
  W: 5.0,    // width
  H: 2.6,    // cavity height (lower body)
  D: 2.5,    // depth
  T: 0.06,   // CAVITY wall thickness (left/right/back/bottom — interior shell)
  HOOD_H: 0.95,
  // Phase 3.9: thick outer FRAME (header/plinth/pillar) protrudes 0.30u in front
  // of the cavity so the doors visually sit *inside* a heavy machined frame.
  FRAME_T: 0.30,
  HEADER_H: 0.32,
  PLINTH_H: 0.30,
  PILLAR_W: 0.10,
  // The doors are recessed just BEHIND the frame's back face → flush with
  // the cavity opening. This keeps the door swing arc free of the frame.
  DOOR_DEPTH: 0.06,
  DOOR_GAP: 0.005,         // air gap between door front face and frame back face
  PILLAR_X: 1.27,          // boundary between main door and side door
};

function MainBody({ doorAngleRef }: { doorAngleRef: React.MutableRefObject<number> }) {
  const onSelectPrinthead = useTwin((st) => st.selectComponent);
  const onSelectRecoater = useTwin((st) => st.selectComponent);
  const selectedId = useTwin((st) => st.selectedComponentId);
  const { matRef: hoodMatRef, setHovered: setHoodHovered } = useHoverPulse(0.02, 0.16);
  const hoodLiftGroupRef = useRef<Group>(null);
  const hoodLiftDampY = useRef(0);

  const { W, H, D, T, HOOD_H } = BODY;
  const halfW = W / 2;
  const halfD = D / 2;

  useFrame((_, d) => {
    const target = isHoodSmartLiftTarget(selectedId) ? HOOD_SMART_LIFT_DELTA : 0;
    damp(hoodLiftDampY, "current", target, HOOD_LIFT_SMOOTH, d);
    const y = hoodLiftDampY.current;
    if (hoodLiftGroupRef.current) hoodLiftGroupRef.current.position.y = y;
    hoodSmartLiftMeters.current = y;
  });

  return (
    <group position={[0.5, 0, 0]}>
      {/* === Bottom (powder-bed floor) === */}
      <RoundedBox args={[W, T, D]} radius={0.02} smoothness={2}
        position={[0, T / 2, 0]} castShadow receiveShadow
        onClick={blockChassis}>
        <meshPhysicalMaterial
          color={PANEL_LIGHT}
          roughness={0.62}
          metalness={0.12}
          clearcoat={0.18}
          clearcoatRoughness={0.5}
        />
      </RoundedBox>

      {/* === Left wall === */}
      <RoundedBox args={[T, H, D]} radius={0.02} smoothness={2}
        position={[-halfW + T / 2, H / 2, 0]} castShadow receiveShadow
        onClick={blockChassis}>
        <meshPhysicalMaterial
          color={PANEL_LIGHT}
          roughness={0.62}
          metalness={0.12}
          clearcoat={0.18}
          clearcoatRoughness={0.5}
        />
      </RoundedBox>

      {/* === Right wall === */}
      <RoundedBox args={[T, H, D]} radius={0.02} smoothness={2}
        position={[halfW - T / 2, H / 2, 0]} castShadow receiveShadow
        onClick={blockChassis}>
        <meshPhysicalMaterial
          color={PANEL_LIGHT}
          roughness={0.62}
          metalness={0.12}
          clearcoat={0.18}
          clearcoatRoughness={0.5}
        />
      </RoundedBox>

      {/* === Back wall (slightly darker for depth) === */}
      <RoundedBox args={[W, H, T]} radius={0.02} smoothness={2}
        position={[0, H / 2, -halfD + T / 2]} castShadow receiveShadow
        onClick={blockChassis}>
        <meshPhysicalMaterial
          color={PANEL_LIGHT_DK}
          roughness={0.7}
          metalness={0.10}
          clearcoat={0.10}
        />
      </RoundedBox>

      {/*
        === Heavy outer frame (Phase 3.9) ===
        Three thick boxes that protrude 0.30u in front of the cavity opening,
        wrapping the door area like an industrial bezel. Casts a clean
        contact shadow on the floor; the doors visually recess into it.
      */}
      {/* Top header */}
      <RoundedBox args={[W, BODY.HEADER_H, BODY.FRAME_T]} radius={0.04} smoothness={3}
        position={[0, H - BODY.HEADER_H / 2, halfD + BODY.FRAME_T / 2]} castShadow receiveShadow
        onClick={blockChassis}>
        <meshPhysicalMaterial
          color={PANEL_LIGHT}
          roughness={0.55}
          metalness={0.18}
          clearcoat={0.25}
          clearcoatRoughness={0.4}
        />
      </RoundedBox>
      {/* Bottom plinth */}
      <RoundedBox args={[W, BODY.PLINTH_H, BODY.FRAME_T]} radius={0.04} smoothness={3}
        position={[0, BODY.PLINTH_H / 2, halfD + BODY.FRAME_T / 2]} castShadow receiveShadow
        onClick={blockChassis}>
        <meshPhysicalMaterial
          color={PANEL_LIGHT}
          roughness={0.55}
          metalness={0.18}
          clearcoat={0.25}
          clearcoatRoughness={0.4}
        />
      </RoundedBox>
      {/* Vertical pillar between main door and side door */}
      <RoundedBox
        args={[BODY.PILLAR_W, H - BODY.HEADER_H - BODY.PLINTH_H, BODY.FRAME_T]}
        radius={0.025}
        smoothness={3}
        position={[BODY.PILLAR_X, (BODY.PLINTH_H + (H - BODY.HEADER_H)) / 2,
                   halfD + BODY.FRAME_T / 2]}
        castShadow
        receiveShadow
        onClick={blockChassis}
      >
        <meshPhysicalMaterial
          color={PANEL_LIGHT}
          roughness={0.55}
          metalness={0.20}
          clearcoat={0.25}
          clearcoatRoughness={0.4}
        />
      </RoundedBox>

      {/*
        Smart lift (Phase 3.11): upper charcoal hood + louvered detail + fume
        stack translate together so the upper cavity (recoater / printhead) is
        not visually capped when those components are focused.
      */}
      <group ref={hoodLiftGroupRef}>
        {/* === Top hood (charcoal, hover-pulse only — not clickable) === */}
        <group
          onClick={blockChassis}
          onPointerOver={(e) => { e.stopPropagation(); setHoodHovered(true); }}
          onPointerOut={() => setHoodHovered(false)}
        >
          <RoundedBox args={[W, HOOD_H, D]} radius={0.06} smoothness={4}
            position={[0, H + HOOD_H / 2, 0]} castShadow receiveShadow>
            <meshPhysicalMaterial
              ref={hoodMatRef}
              color={HOOD_CHARCOAL}
              roughness={0.7}
              metalness={0.18}
              clearcoat={0.12}
              clearcoatRoughness={0.55}
            />
          </RoundedBox>
        </group>

        {/* Louver grooves — flush PLANES on top of the hood (no z-fighting) */}
        {Array.from({ length: 5 }).map((_, i) => (
          <mesh
            key={`louver-${i}`}
            position={[0, H + HOOD_H + 0.0015, -halfD + 0.4 + i * 0.4]}
            rotation={[-Math.PI / 2, 0, 0]}
            onClick={blockChassis}
          >
            <planeGeometry args={[W - 0.5, 0.045]} />
            <meshStandardMaterial
              color="#161719"
              roughness={0.92}
              metalness={0.05}
              polygonOffset
              polygonOffsetFactor={-1}
              polygonOffsetUnits={-1}
            />
          </mesh>
        ))}

        {/* Exhaust hopper / vacuum cone (Fume Extraction) — moves with the hood cap */}
        <group position={[-0.8, H + HOOD_H, 0]} onClick={blockChassis}>
          <mesh castShadow>
            <cylinderGeometry args={[0.16, 0.32, 0.5, 24]} />
            <meshStandardMaterial color={MATTE_BLACK} roughness={0.78} metalness={0.1} />
          </mesh>
          <RoundedBox args={[0.85, 0.4, 0.85]} radius={0.05} smoothness={3}
            position={[0, 0.32, 0]} castShadow>
            <meshStandardMaterial color={MATTE_BLACK} roughness={0.78} metalness={0.1} />
          </RoundedBox>
          <mesh position={[0, 0.62, 0]} castShadow>
            <cylinderGeometry args={[0.18, 0.18, 0.18, 24]} />
            <meshStandardMaterial color={MATTE_BLACK} roughness={0.55} metalness={0.4} />
          </mesh>
        </group>
      </group>

      {/* HP METAL JET PRINT label strip — sits on the FRONT face of the
          protruding header so it reads on top of the heavy frame. */}
      <RoundedBox args={[1.5, 0.13, 0.04]} radius={0.02} smoothness={2}
        position={[1.7, H - BODY.HEADER_H * 0.55, halfD + BODY.FRAME_T + 0.022]}
        onClick={blockChassis}>
        <meshStandardMaterial color="#e4e7eb" roughness={0.55} metalness={0.1} />
      </RoundedBox>

      {/* Hinged main door (covers the left ~half of the front opening) */}
      <HingedDoor
        doorAngleRef={doorAngleRef}
        onClick={() => onSelectPrinthead("nozzle_plate")}
      />

      {/* Side door (right) — covers the right ~third of the front opening */}
      <SideDoor
        onClick={() => onSelectRecoater("recoater_blade")}
      />
    </group>
  );
}

/* ── Hinged main door (Phase 3.9: HP logo + recessed inside thick frame) ── */

function HingedDoor({
  doorAngleRef,
  onClick,
}: {
  doorAngleRef: React.MutableRefObject<number>;
  onClick: () => void;
}) {
  const hingeRef = useRef<Group>(null);
  const { matRef, setHovered } = useHoverPulse(0.04, 0.32);

  useFrame((_state, delta) => {
    if (hingeRef.current) {
      damp(hingeRef.current.rotation, "y", doorAngleRef.current, DOOR_SMOOTH, delta);
    }
  });

  // Door spans from the body's left edge to the central pillar.
  // Width is computed from PILLAR_X so it never overlaps or gaps.
  const HINGE_X = -BODY.W / 2 + 0.04;       // ≈ −2.46, just inside the cavity wall
  const W = BODY.PILLAR_X - HINGE_X - 0.04; // far edge ~0.04u left of pillar
  const H = BODY.H - BODY.HEADER_H - BODY.PLINTH_H - 0.04; // fits between header & plinth
  const D = BODY.DOOR_DEPTH;
  // Door recessed BEHIND the protruding frame's back face.
  const HINGE_Z = BODY.D / 2 - BODY.DOOR_GAP - D / 2;
  const DOOR_Y = BODY.PLINTH_H + H / 2;

  return (
    <group ref={hingeRef} position={[HINGE_X, DOOR_Y, HINGE_Z]}>
      <group
        onClick={(e) => { e.stopPropagation(); onClick(); }}
        onPointerOver={(e) => { e.stopPropagation(); setHovered(true); document.body.style.cursor = "pointer"; }}
        onPointerOut={() => { setHovered(false); document.body.style.cursor = ""; }}
      >
        {/* Door panel (semi-gloss painted metal) */}
        <RoundedBox args={[W, H, D]} radius={0.025} smoothness={3}
          position={[W / 2, 0, 0]} castShadow>
          <meshPhysicalMaterial
            ref={matRef}
            color={PANEL_LIGHT}
            roughness={0.42}
            metalness={0.32}
            clearcoat={0.5}
            clearcoatRoughness={0.4}
            emissive={ACCENT_GLOW}
            emissiveIntensity={0.04}
          />
        </RoundedBox>

        {/* Vertical handle accent (cyan) on hinge side */}
        <RoundedBox args={[0.05, 1.1, 0.02]} radius={0.01} smoothness={2}
          position={[0.18, 0, D / 2 + 0.01]}>
          <meshStandardMaterial
            color={ACCENT_CYAN_SOFT}
            emissive={ACCENT_CYAN_SOFT}
            emissiveIntensity={0.7}
            roughness={0.4}
            metalness={0.2}
          />
        </RoundedBox>

        {/*
          === HP brand logo ===
          Renders the official HP corporate mark from
          `frontend/public/hp-logo.png` (the canonical asset shipped with
          the challenge brief). We use a flat textured plane rather than
          rebuilding the mark procedurally so colour and proportions stay
          faithful to HP's brand guidelines.
        */}
        <HpLogo position={[W / 2, 0.0, D / 2 + 0.012]} size={0.78} />
      </group>
    </group>
  );
}

/**
 * Self-contained HP logo: textured plane carrying the official HP brand
 * asset. `size` is the side length of the square plane (the source PNG is
 * 1280×1278, effectively square). The texture has an alpha channel so the
 * plane simply blends onto the door surface — no procedural recreation,
 * no z-fight halo.
 */
function HpLogo({
  position,
  size,
}: {
  position: [number, number, number];
  size: number;
}) {
  const texture = useTexture("/hp-logo.png");
  // Configure the asset for correct sRGB rendering and STRAIGHT (not
  // premultiplied) alpha so the transparent corners of the PNG don't get
  // composited as black against the door panel.
  texture.colorSpace = SRGBColorSpace;
  texture.premultipliedAlpha = false;
  return (
    <mesh position={position} raycast={noRaycast}>
      <planeGeometry args={[size, size]} />
      <meshBasicMaterial
        map={texture}
        transparent
        // alphaTest discards near-zero-alpha texels entirely so even if a
        // GPU/driver loses the blend equation we never see the black RGB
        // payload underneath the alpha mask.
        alphaTest={0.05}
        toneMapped={false}
      />
    </mesh>
  );
}

/* ── Side door (right, NOT hinged) ─────────────────────────────────────── */

function SideDoor({ onClick }: { onClick: () => void }) {
  const { matRef, setHovered } = useHoverPulse(0.04, 0.30);

  // Side door fits between pillar and right wall, same vertical bounds as
  // the main door, recessed behind the thick frame.
  const LEFT = BODY.PILLAR_X + BODY.PILLAR_W / 2 + 0.02;
  const RIGHT = BODY.W / 2 - 0.04;
  const W = RIGHT - LEFT;
  const H = BODY.H - BODY.HEADER_H - BODY.PLINTH_H - 0.04;
  const D = BODY.DOOR_DEPTH;
  const X_CENTER = (LEFT + RIGHT) / 2;
  const Y_CENTER = BODY.PLINTH_H + H / 2;
  const Z_CENTER = BODY.D / 2 - BODY.DOOR_GAP - D / 2;

  return (
    <group
      position={[X_CENTER, Y_CENTER, Z_CENTER]}
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      onPointerOver={(e) => { e.stopPropagation(); setHovered(true); document.body.style.cursor = "pointer"; }}
      onPointerOut={() => { setHovered(false); document.body.style.cursor = ""; }}
    >
      <RoundedBox args={[W, H, D]} radius={0.025} smoothness={3} castShadow>
        <meshPhysicalMaterial
          ref={matRef}
          color={PANEL_LIGHT}
          roughness={0.42}
          metalness={0.32}
          clearcoat={0.5}
          clearcoatRoughness={0.4}
          emissive={ACCENT_GLOW}
          emissiveIntensity={0.04}
        />
      </RoundedBox>
      {/* Cyan handle accent — anchored relative to door's left edge */}
      <RoundedBox args={[0.05, H * 0.55, 0.02]} radius={0.01} smoothness={2}
        position={[-W / 2 + 0.10, 0, D / 2 + 0.005]}>
        <meshStandardMaterial
          color={ACCENT_CYAN_SOFT}
          emissive={ACCENT_CYAN_SOFT}
          emissiveIntensity={0.7}
          roughness={0.4}
          metalness={0.2}
        />
      </RoundedBox>
      {/* Vertical vent slits */}
      {Array.from({ length: 4 }).map((_, i) => (
        <RoundedBox key={`vent-${i}`} args={[0.02, H * 0.5, 0.02]} radius={0.005} smoothness={2}
          position={[W * 0.05 + i * 0.06, -H * 0.08, D / 2 + 0.005]}>
          <meshStandardMaterial color="#1a1c1f" roughness={0.7} metalness={0.4} />
        </RoundedBox>
      ))}
    </group>
  );
}

/* ── HP signature light bar (highly emissive, never fades) ──────────────── */

function LightBar() {
  // Horizontal cyan strip mounted on the FRONT face of the thick header,
  // running along the right portion of the chassis above the side door.
  const Z_FRONT = BODY.D / 2 + BODY.FRAME_T + 0.025;
  const Y = BODY.H - BODY.HEADER_H - 0.07;
  return (
    <group position={[0.5, 0, 0]}>
      <mesh position={[1.95, Y, Z_FRONT]} onClick={blockChassis}>
        <boxGeometry args={[1.4, 0.06, 0.06]} />
        <meshStandardMaterial
          color={ACCENT_CYAN}
          emissive={ACCENT_CYAN}
          emissiveIntensity={2}
          toneMapped={false}
          roughness={0.3}
          metalness={0.1}
        />
      </mesh>
      {/* Subtle bloom underlay — wider, dimmer, recessed */}
      <mesh position={[1.95, Y, Z_FRONT - 0.005]} onClick={blockChassis}>
        <planeGeometry args={[1.7, 0.16]} />
        <meshBasicMaterial
          color={ACCENT_CYAN}
          transparent
          opacity={0.15}
          toneMapped={false}
        />
      </mesh>
    </group>
  );
}

/* ── Sanctum lighting — "surgical theater" inside the cavity ────────────── */

/**
 * RectAreaLight is the right tool for this job: a wide, soft, diffuse plane
 * source mounted to the inside roof of the cavity, pointing straight down.
 * It only illuminates `MeshStandardMaterial` / `MeshPhysicalMaterial`
 * (which is everything we use), so the moment the chassis starts to fade
 * the entire interior reads like an Apple product spotlight pass.
 *
 * Notes:
 *  • We ramp `intensity` from 0 → MAX in lock-step with `shellOpacityRef`,
 *    so the light is OFF when the door is closed (no light pollution
 *    leaking outside the chassis) and FULL the moment the chassis
 *    dissolves to 0.2.
 *  • The light is parented to the body group (`position={[0.5, 0, 0]}`).
 *  • A small clinical accent SpotLight stays on as a top-down rim, so
 *    metallic edges of the recoater pop even before the area light ramps.
 */
const SANCTUM_MAX = 22;

function SanctumLight({ shellOpacityRef }: { shellOpacityRef: React.MutableRefObject<number> }) {
  const areaRef = useRef<RectAreaLight>(null);
  const accentRef = useRef<RectAreaLight>(null);

  useFrame(() => {
    // Map shellOpacity ∈ [0.2, 1.0] → t ∈ [1.0, 0.0]
    const t = Math.max(0, Math.min(1, (1.0 - shellOpacityRef.current) / 0.8));
    if (areaRef.current) areaRef.current.intensity = t * SANCTUM_MAX;
    if (accentRef.current) accentRef.current.intensity = t * 6;
  });

  return (
    <group position={[0.5, 0, 0]}>
      {/* Main soft fill — wide rectangle on the cavity ceiling, pointing down */}
      <rectAreaLight
        ref={areaRef}
        position={[0, 2.55, 0]}
        rotation={[-Math.PI / 2, 0, 0]}
        width={3.6}
        height={2.0}
        intensity={0}
        color="#f4f6ff"
      />
      {/* Smaller cool accent slightly forward — gives a defined highlight along
          the recoater rail and bed surface for that "operating-room" sheen. */}
      <rectAreaLight
        ref={accentRef}
        position={[0, 2.4, 0.6]}
        rotation={[-Math.PI / 2.2, 0, 0]}
        width={2.2}
        height={0.6}
        intensity={0}
        color="#dde6ff"
      />
    </group>
  );
}

/* ── Print "fusing" light — warm point light pulsing inside the chamber ── */

/**
 * PrintFusingLight — driven by the same `executingPrint` flag as the recoater
 * sweep. Lives near the powder-bed surface so the warm wash bounces off the
 * brushed-steel internals and reads through the open door without ever
 * leaking outside the chassis (point light, sharp falloff).
 *
 * Two ramps stacked: a slow envelope (eases over ~250 ms when the action
 * toggles) and a fast sinusoid (the laser/fusing pulse). Multiplying them
 * keeps the fade-in clean and the heartbeat clearly readable.
 */
function PrintFusingLight() {
  const executingPrint = useTwin((s) => s.executingPrint);
  const lightRef = useRef<PointLight>(null);
  const envelope = useRef(0);

  useFrame((state, delta) => {
    const l = lightRef.current;
    if (!l) return;
    damp(envelope, "current", executingPrint ? 1 : 0, 0.25, delta);
    const env = envelope.current;
    if (env < 0.001) {
      l.intensity = 0;
      return;
    }
    const phase = (state.clock.elapsedTime * (2 * Math.PI)) / PRINT_LIGHT_PERIOD;
    // 0..1 sinusoid, biased so the light never fully dies between pulses.
    const beat = 0.55 + 0.45 * Math.sin(phase);
    l.intensity = env * beat * PRINT_LIGHT_PEAK;
  });

  return (
    <pointLight
      ref={lightRef}
      position={[0.5, 0.95, 0]}
      color="#ffb070"
      distance={3.2}
      decay={1.6}
      intensity={0}
    />
  );
}

/* ── Floor feet (always opaque, never fade) ─────────────────────────────── */

function Feet() {
  return (
    <group position={[0.5, 0, 0]}>
      {[
        [-2.4, -1.2],
        [2.4, -1.2],
        [-2.4, 1.2],
        [2.4, 1.2],
      ].map(([fx, fz], i) => (
        <mesh key={`foot-${i}`} position={[fx, -0.05, fz]} castShadow onClick={blockChassis}>
          <cylinderGeometry args={[0.10, 0.13, 0.18, 14]} />
          <meshStandardMaterial color="#3a3c40" roughness={0.4} metalness={0.6} />
        </mesh>
      ))}
    </group>
  );
}

/* ── Internal stylised parts (live inside the cavity) ───────────────────── */

interface InternalDef {
  id: ComponentId;
  memberIds: ComponentId[];
  basePosition: [number, number, number];
  explodeY: number;
  baseColor: string;
  /**
   * Invisible enlarged hitbox for the InternalPart click target. Helpful
   * because the visible meshes (cylinders, thin rails, slender carriage)
   * are tiny silhouettes when seen through the door opening — without an
   * enlarged hitbox the user has to pixel-hunt.
   */
  hitbox: [number, number, number];
  render: (p: {
    active: boolean;
    hovered: boolean;
    status: OperationalStatus;
    baseColor: string;
    onPick: (e: ThreeEvent<MouseEvent>) => void;
  }) => ReactElement;
}

const INTERNAL_PARTS: InternalDef[] = [
  /* === Build Unit (powder bed) — slate housing + warm metal-powder bed.
       Real metal powder reads as a warm silver-tan under chamber light, which
       gives the build unit its own colour identity vs the cool-grey chassis. */
  {
    id: "heating_element",
    memberIds: ["heating_element", "insulation_panel"],
    basePosition: [0.5, 0.6, 0],
    explodeY: -0.2,
    baseColor: "#3a3d44",
    hitbox: [2.6, 0.9, 1.8],
    render: ({ active, hovered, status, baseColor, onPick }) => (
      <group>
        {/* Build Unit housing — slightly dark slate, supports the powder bed */}
        <RoundedBox
          args={[2.4, 0.4, 1.6]}
          radius={0.04}
          smoothness={3}
          castShadow
          receiveShadow
          onClick={onPick}
        >
          <PremiumInternalMaterial baseColor={baseColor} status={status} active={active} hovered={hovered}
            metalness={0.45} roughness={0.55} clearcoat={0.25} />
          <Outlines
            color={ACCENT_CYAN}
            thickness={0.02}
            transparent
            opacity={0}
          />
        </RoundedBox>
        {/* Powder bed surface — light matte silver to bounce the sanctum light */}
        <RoundedBox
          args={[2.05, 0.05, 1.32]}
          radius={0.012}
          smoothness={3}
          position={[0, 0.225, 0]}
          receiveShadow
          onClick={onPick}
        >
          <PowderBedSelectionMaterial active={active} />
        </RoundedBox>
        {/* Subtle bed border (machined frame) for definition */}
        <RoundedBox
          args={[2.12, 0.03, 1.38]}
          radius={0.012}
          smoothness={2}
          position={[0, 0.215, 0]}
          onClick={onPick}
        >
          <meshStandardMaterial color="#7e828a" roughness={0.45} metalness={0.7} />
        </RoundedBox>
      </group>
    ),
  },

  /* === Printhead Carriage — high-contrast dark ceramic + amber firing LEDs.
       LEDs are warm amber (not the chassis cyan) so the printhead reads as a
       different functional system from the cooling/IO indicators around it. */
  {
    id: "nozzle_plate",
    memberIds: ["nozzle_plate", "thermal_resistor"],
    basePosition: [0.5, 1.4, 0],
    explodeY: 0.35,
    baseColor: "#1a1c20",
    hitbox: [2.0, 0.7, 1.0],
    render: ({ active, hovered, status, baseColor, onPick }) => (
      <group>
        {/* Carriage body — matte dark ceramic */}
        <RoundedBox args={[1.8, 0.32, 0.7]} radius={0.04} smoothness={3} castShadow onClick={onPick}>
          <PremiumInternalMaterial baseColor={baseColor} status={status} active={active} hovered={hovered}
            metalness={0.18} roughness={0.62} clearcoat={0.18} />
          <Outlines
            color={ACCENT_CYAN}
            thickness={0.02}
            transparent
            opacity={0}
          />
        </RoundedBox>
        {/* Nozzle/firing plate underside — glossy black ceramic */}
        <RoundedBox
          args={[1.7, 0.05, 0.6]}
          radius={0.015}
          smoothness={2}
          position={[0, -0.18, 0]}
          castShadow
          onClick={onPick}
        >
          <meshPhysicalMaterial
            color="#0c0d10"
            roughness={0.22}
            metalness={0.4}
            clearcoat={0.85}
            clearcoatRoughness={0.15}
          />
        </RoundedBox>
        {/* Firing-array indicator LED strip — warm amber so the printhead
            reads as its own functional system, not as part of the chassis
            cyan light bar. Centre LED is the "active firing" beacon. */}
        {[-0.6, -0.3, 0, 0.3, 0.6].map((x, i) => (
          <mesh key={`led-${i}`} position={[x, 0.05, 0.36]} onClick={onPick}>
            <sphereGeometry args={[0.025, 16, 16]} />
            <meshStandardMaterial
              color="#ffb663"
              emissive="#ffa84a"
              emissiveIntensity={i === 2 ? 1.7 : 1.1}
              toneMapped={false}
              roughness={0.3}
              metalness={0.1}
            />
          </mesh>
        ))}
        {/* Tiny brushed-steel mount tabs on top */}
        {[-0.7, 0.7].map((x, i) => (
          <RoundedBox
            key={`tab-${i}`}
            args={[0.18, 0.06, 0.18]}
            radius={0.015}
            smoothness={2}
            position={[x, 0.20, 0]}
            castShadow
            onClick={onPick}
          >
            <meshStandardMaterial color="#5e6168" roughness={0.32} metalness={0.82} />
          </RoundedBox>
        ))}
        {/* Upper cross-gantry read — structural tie under the hood line */}
        <RoundedBox
          args={[1.6, 0.035, 0.035]}
          radius={0.01}
          smoothness={2}
          position={[0, 0.20, 0.22]}
          castShadow
          onClick={onPick}
        >
          <meshStandardMaterial color="#2a2c31" roughness={0.55} metalness={0.55} />
        </RoundedBox>
      </group>
    ),
  },

  /* === Recoater — brushed stainless steel rails + blade + motor === */
  {
    id: "recoater_blade",
    memberIds: ["recoater_blade", "recoater_motor"],
    basePosition: [0.5, 2.0, 0],
    explodeY: 0.45,
    baseColor: "#9aa0a8",
    hitbox: [3.0, 0.6, 1.8],
    render: ({ active, hovered, status, baseColor, onPick }) => (
      <group>
        {/* Rails — brushed stainless steel: high metalness, mid-low roughness */}
        <mesh
          castShadow
          position={[0, 0, -0.7]}
          rotation={[0, 0, Math.PI / 2]}
          onClick={onPick}
        >
          <cylinderGeometry args={[0.045, 0.045, 2.4, 16]} />
          <meshPhysicalMaterial
            color="#9aa0a8"
            metalness={0.88}
            roughness={0.28}
            clearcoat={0.4}
            clearcoatRoughness={0.35}
            envMapIntensity={1.5}
          />
        </mesh>
        <mesh
          castShadow
          position={[0, 0, 0.7]}
          rotation={[0, 0, Math.PI / 2]}
          onClick={onPick}
        >
          <cylinderGeometry args={[0.045, 0.045, 2.4, 16]} />
          <meshPhysicalMaterial
            color="#9aa0a8"
            metalness={0.88}
            roughness={0.28}
            clearcoat={0.4}
            clearcoatRoughness={0.35}
            envMapIntensity={1.5}
          />
        </mesh>
        {/* Roller blade — brushed steel, slightly satin so the status tint reads */}
        <RoundedBox
          args={[0.32, 0.18, 1.55]}
          radius={0.03}
          smoothness={3}
          castShadow
          onClick={onPick}
        >
          <PremiumInternalMaterial baseColor={baseColor} status={status} active={active} hovered={hovered}
            metalness={0.8} roughness={0.30} clearcoat={0.5} />
          <Outlines
            color={ACCENT_CYAN}
            thickness={0.02}
            transparent
            opacity={0}
          />
        </RoundedBox>
        {/* Drive motor housing — darker machined block */}
        <RoundedBox
          args={[0.36, 0.36, 0.36]}
          radius={0.05}
          smoothness={3}
          position={[1.20, 0, 0]}
          castShadow
          onClick={onPick}
        >
          <PremiumInternalMaterial baseColor="#1f2126" status={status} active={active} hovered={hovered}
            metalness={0.6} roughness={0.32} clearcoat={0.45} />
        </RoundedBox>
        {/*
          Recoater drive motor (HP spec): stacked brushed cylinder — reads clearly
          after smart-lift reveals the top cavity; sits beside the dark housing.
        */}
        <mesh
          position={[1.2, 0, 0.28]}
          castShadow
          rotation={[0, 0, Math.PI / 2]}
          onClick={onPick}
        >
          <cylinderGeometry args={[0.11, 0.11, 0.2, 20]} />
          <meshPhysicalMaterial
            color="#b8bfc8"
            metalness={0.9}
            roughness={0.25}
            clearcoat={0.35}
            clearcoatRoughness={0.4}
            envMapIntensity={1.35}
          />
        </mesh>
        <mesh
          position={[1.2, 0, 0.42]}
          castShadow
          rotation={[0, 0, Math.PI / 2]}
          onClick={onPick}
        >
          <cylinderGeometry args={[0.09, 0.07, 0.1, 16]} />
          <meshPhysicalMaterial
            color="#8a9099"
            metalness={0.85}
            roughness={0.35}
            envMapIntensity={1.1}
          />
        </mesh>
        {/* Motor status LED */}
        <mesh position={[1.20, 0.10, 0.19]} onClick={onPick}>
          <sphereGeometry args={[0.022, 12, 12]} />
          <meshStandardMaterial
            color="#5fd185"
            emissive="#5fd185"
            emissiveIntensity={1.4}
            toneMapped={false}
          />
        </mesh>
      </group>
    ),
  },
];

interface PremiumInternalMaterialProps {
  baseColor: string;
  status: OperationalStatus;
  active: boolean;
  hovered: boolean;
  metalness?: number;
  roughness?: number;
  clearcoat?: number;
}

const BLACK = new Color(0, 0, 0);

function PremiumInternalMaterial({
  baseColor,
  status,
  active,
  hovered,
  metalness = 0.55,
  roughness = 0.32,
  clearcoat = 0.45,
}: PremiumInternalMaterialProps) {
  const matRef = useRef<MeshPhysicalMaterial | null>(null);
  const selBlend = useRef(0);
  const tint = tintFor(status);
  const tintC = useMemo(() => (tint ? new Color(tint) : null), [tint]);

  useFrame((state, d) => {
    const m = matRef.current;
    if (!m) return;
    // Faulted parts always carry their warning tint regardless of selection.
    if (tintC) {
      m.emissive.copy(tintC);
      m.emissiveIntensity = active ? 0.6 : hovered ? 0.42 : 0.22;
      return;
    }
    damp(selBlend, "current", active ? 1 : 0, SELECTION_SMOOTH, d);
    const sb = selBlend.current;
    if (sb > 0.005) {
      // === Selection: intermittent cyan glow ===
      // Wide-amplitude sine on emissiveIntensity so the part visibly
      // breathes between dim (≈0.20) and brilliant (≈1.20). Period ~1.6 s
      // — slow enough to read as deliberate, fast enough to feel alive.
      // Color is set directly (no damp) so the pulse hits its peaks
      // without being averaged out by the easing.
      const phase = state.clock.elapsedTime * 3.9;
      const pulse = 0.5 + 0.5 * Math.sin(phase); // 0..1
      m.emissive.copy(SELECTION_EMISSIVE);
      m.emissiveIntensity = (0.20 + 1.00 * pulse) * sb;
    } else if (hovered) {
      m.emissive.lerp(ACCENT_GLOW, 0.2);
      damp(m, "emissiveIntensity", 0.22, 0.2, d);
    } else {
      // Idle — a very faint accent breath (8 s period, peak 0.09) keeps
      // clickable parts visibly different from the static chassis without
      // pulling focus.
      const idleBreath = 0.06 + 0.03 * (0.5 + 0.5 * Math.sin(state.clock.elapsedTime * 0.78));
      m.emissive.lerp(ACCENT_GLOW, 0.05);
      damp(m, "emissiveIntensity", idleBreath, 0.22, d);
    }
  });

  return (
    <meshPhysicalMaterial
      ref={matRef}
      color={baseColor}
      metalness={metalness}
      roughness={roughness}
      clearcoat={clearcoat}
      clearcoatRoughness={0.55}
      emissive={BLACK}
      emissiveIntensity={0.04}
      envMapIntensity={1.15}
    />
  );
}

/**
 * Build Unit powder top — separate material so "selection" can lerp
 * emissive when the part is the camera focus, without key-snapping.
 */
function PowderBedSelectionMaterial({ active }: { active: boolean }) {
  const matRef = useRef<MeshPhysicalMaterial | null>(null);
  const t = useRef(0);
  useFrame((_, d) => {
    damp(t, "current", active ? 1 : 0, SELECTION_SMOOTH, d);
    const m = matRef.current;
    if (!m) return;
    m.emissive.lerpColors(BLACK, SELECTION_EMISSIVE, t.current * 0.85);
    m.emissiveIntensity = 0.01 + 0.38 * t.current;
  });
  return (
    <meshPhysicalMaterial
      ref={matRef}
      color="#c8ccd0"
      roughness={0.55}
      metalness={0.78}
      clearcoat={0.35}
      clearcoatRoughness={0.5}
      envMapIntensity={1.4}
      emissive={BLACK}
      emissiveIntensity={0.01}
    />
  );
}

function InternalPart({ def }: { def: InternalDef }) {
  const snapshot = useTwin((s) => s.snapshot);
  const selectedId = useTwin((s) => s.selectedComponentId);
  const setSelected = useTwin((s) => s.selectComponent);
  const executingPrint = useTwin((s) => s.executingPrint);
  const groupRef = useRef<Group>(null);
  const outlineLineMat = useRef<LineBasicMaterial | null>(null);
  const outlineOp = useRef(0);
  // Damped envelope so the recoater eases in/out of its sweep instead of
  // jump-cutting when `executingPrint` toggles.
  const printEnvelope = useRef(0);
  const [hovered, setHovered] = useState(false);
  useCursor(hovered);

  const isRecoater = def.id === "recoater_blade";

  const status = worstStatus(snapshot, def.memberIds);
  const isActive =
    selectedId != null &&
    (selectedId === def.id || (def.memberIds as ComponentId[]).includes(selectedId));

  const pick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    setSelected(isActive ? null : def.id);
  };

  useLayoutEffect(() => {
    const id2 = requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (!groupRef.current) return;
        groupRef.current.traverse((o) => {
          if (outlineLineMat.current) return;
          if (!(o as LineSegments).isLineSegments) return;
          const mat = (o as LineSegments).material;
          if (Array.isArray(mat) || !mat) return;
          if ((mat as LineBasicMaterial).isLineBasicMaterial) {
            outlineLineMat.current = mat as LineBasicMaterial;
            outlineLineMat.current.transparent = true;
            outlineLineMat.current.opacity = 0;
            outlineLineMat.current.depthTest = true;
            outlineLineMat.current.needsUpdate = true;
          }
        });
      });
    });
    return () => cancelAnimationFrame(id2);
  }, [def.id]);

  useFrame((state, delta) => {
    const g = groupRef.current;
    if (!g) return;
    const targetScale = isActive ? 1.04 : hovered ? 1.02 : 1;
    damp3(g.scale, [targetScale, targetScale, targetScale], SCALE_SMOOTH, delta);
    const exploded = selectedId !== null;
    const targetY = def.basePosition[1] + (exploded ? def.explodeY : 0);
    damp(g.position, "y", targetY, POSITION_SMOOTH, delta);
    damp(outlineOp, "current", isActive ? 0.8 : 0, OUTLINE_SMOOTH, delta);
    if (outlineLineMat.current) {
      outlineLineMat.current.opacity = outlineOp.current;
      outlineLineMat.current.needsUpdate = true;
    }

    // Mock "Execute Print" — recoater sweeps across the powder bed in Z while
    // the warm chamber light pulses (handled separately in <PrintFusingLight />).
    // The envelope eases in/out so toggling the action never snaps the mesh.
    if (isRecoater) {
      damp(printEnvelope, "current", executingPrint ? 1 : 0, PRINT_ENVELOPE_SMOOTH, delta);
      const env = printEnvelope.current;
      const phase = (state.clock.elapsedTime * (2 * Math.PI)) / PRINT_RECOATER_PERIOD;
      const offset = Math.sin(phase) * PRINT_RECOATER_TRAVEL * env;
      const baseZ = def.basePosition[2];
      damp(g.position, "z", baseZ + offset, 0.05, delta);
    }
  });

  return (
    <group
      ref={groupRef}
      position={def.basePosition}
      onPointerOver={(e) => { e.stopPropagation(); setHovered(true); }}
      onPointerOut={() => setHovered(false)}
    >
      {def.render({
        active: isActive,
        hovered,
        status,
        baseColor: def.baseColor,
        onPick: pick,
      })}
      {/*
        Invisible enlarged hitbox — colorWrite/depthWrite off so it never
        renders into colour or depth buffers, but the raycaster still picks
        it up. Greatly improves click reliability on slender internals.
      */}
      <mesh onClick={pick}>
        <boxGeometry args={def.hitbox} />
        <meshBasicMaterial colorWrite={false} depthWrite={false} />
      </mesh>
    </group>
  );
}

function Internals() {
  return (
    <group>
      {INTERNAL_PARTS.map((def) => (
        <InternalPart key={def.id} def={def} />
      ))}
    </group>
  );
}

/* ── Public ─────────────────────────────────────────────────────────────── */

export function MachineModel() {
  const selectedId = useTwin((s) => s.selectedComponentId);

  // Refs are written once per frame in the parent and READ by children →
  // zero React re-renders, perfectly synchronised across walls + door + light.
  const shellOpacityRef = useRef(1.0);
  const doorAngleRef = useRef(0);

  useFrame((_state, delta) => {
    const focused = selectedId !== null;
    const targetOpacity = focused ? SHELL_DIM_OPACITY : 1.0;
    const targetAngle = focused ? DOOR_OPEN_ANGLE : 0;

    const dampScalar = (ref: React.MutableRefObject<number>, to: number, smooth: number) => {
      const lambda = Math.exp(-delta / smooth);
      ref.current = to + (ref.current - to) * lambda;
    };
    dampScalar(shellOpacityRef, targetOpacity, SHELL_SMOOTH);
    dampScalar(doorAngleRef, targetAngle, DOOR_SMOOTH);
  });

  return (
    <group>
      {/* Everything chassis-related fades together when a part is focused. */}
      <FadeGroup opacityRef={shellOpacityRef}>
        <ControlTower />
        <MainBody doorAngleRef={doorAngleRef} />
      </FadeGroup>

      {/* Inside the cavity — never fades. */}
      <Internals />

      {/* Always-on emissive accent — does NOT fade with the chassis. */}
      <LightBar />

      {/* Lifts intensity in lock-step with the chassis fade. */}
      <SanctumLight shellOpacityRef={shellOpacityRef} />

      {/* Warm fusing pulse — only on while `executingPrint` is true. */}
      <PrintFusingLight />

      {/* Static feet — never fade. */}
      <Feet />
    </group>
  );
}
