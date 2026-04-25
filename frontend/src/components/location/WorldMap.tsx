import { useEffect, useRef, useState, type RefObject } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Html, OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { feature } from "topojson-client";
import type { Feature, FeatureCollection, MultiPolygon, Polygon, Position } from "geojson";
import worldRaw from "world-atlas/land-110m.json";
import { CITIES, type City } from "./cities";
import {
  buildContinentHatchGeometry,
  buildContinentLineGeometry,
  buildGraticuleGeometry,
  latLonToVec3,
} from "./geo3d";

/**
 * WorldMap (v2) — R3F 3D globe.
 *
 *   • Sphere (light grey ocean) with three line layers:
 *       1. Subtle global graticule (15° step, ~6% opacity).
 *       2. Continent-clipped scanline hatch (parallels + meridians inside
 *          land polygons, ~18% opacity) — gives every landmass an
 *          engraved-paper texture.
 *       3. Continent outlines, animated via setDrawRange(0..total*progress)
 *          for a left-to-right pen-draw across the sphere.
 *   • Intro: 200 ms blank → camera dollies z=6→3.2 over 3.5 s + continents
 *     paint progressively → markers fade-in staggered → onIntroComplete
 *     fires after markers settle. Then OrbitControls activate.
 *   • Same prop signature as v1 so LocationSelectorPage didn't change.
 */

// ── Tunables ────────────────────────────────────────────────────────────── //
const GLOBE_RADIUS = 1.5;
const Z_FAR = 6;
const Z_NEAR = 3.2;
const Z_MIN = 2.5;
const Z_MAX = 6;
const BLANK_DELAY_MS = 200;
const INTRO_TOTAL_MS = 3500;
const MARKER_FADE_MS = 280;
const MARKER_STAGGER_MS = 80;
const PULSE_RING_MS = 700;
const APPLE_EASE_CSS = "cubic-bezier(0.16, 1, 0.3, 1)";

const MARKER_DEFAULT_R = 0.018;
const MARKER_HOVER_R = 0.030;
const MARKER_SELECTED_RING_INNER = 0.040;
const MARKER_SELECTED_RING_OUTER = 0.048;
const MARKER_SELECTED_DOT_R = 0.013;
const MARKER_HIT_R = 0.060;

// ── World data + pre-built geometries ───────────────────────────────────── //
// world-atlas/land-110m.json wraps the land in a GeometryCollection. Calling
// feature() on it yields a FeatureCollection — flatten every Polygon /
// MultiPolygon into one combined MultiPolygon so geo3d.ts can iterate
// `geometry.coordinates` uniformly.
type WorldTopology = Parameters<typeof feature>[0];
type FeatureInput = Parameters<typeof feature>[1];
const topology = worldRaw as unknown as WorldTopology;
const rawLand = (worldRaw as unknown as { objects: { land: FeatureInput } }).objects.land;
const landFc = feature(topology, rawLand) as FeatureCollection<MultiPolygon | Polygon>;
const allPolygons: Position[][][] = [];
for (const f of landFc.features) {
  if (f.geometry.type === "MultiPolygon") {
    for (const polygon of f.geometry.coordinates) allPolygons.push(polygon);
  } else if (f.geometry.type === "Polygon") {
    allPolygons.push(f.geometry.coordinates);
  }
}
const landFeature: Feature<MultiPolygon> = {
  type: "Feature",
  properties: {},
  geometry: { type: "MultiPolygon", coordinates: allPolygons },
};

const continentResult = buildContinentLineGeometry(landFeature, GLOBE_RADIUS * 1.0015);
const graticuleGeometry = buildGraticuleGeometry(GLOBE_RADIUS * 1.0005, 15);
const hatchGeometry = buildContinentHatchGeometry(landFeature, GLOBE_RADIUS * 1.001, 4, 6);

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

interface WorldMapProps {
  highlightedCityId: string | null;
  confirmedCityId: string | null;
  onMarkerClick: (city: City) => void;
  skipIntroAnimation: boolean;
  onIntroComplete?: () => void;
}

export function WorldMap(props: WorldMapProps) {
  return (
    <div className="absolute inset-0">
      <style>{`
        @keyframes locMarkerPulse {
          0%   { transform: scale(0.6); opacity: 0.85; }
          100% { transform: scale(2.4); opacity: 0;    }
        }
      `}</style>
      <Canvas
        camera={{
          position: [0, 0, props.skipIntroAnimation ? Z_NEAR : Z_FAR],
          fov: 35,
          near: 0.1,
          far: 100,
        }}
        dpr={[1, 2]}
        style={{ background: "transparent", touchAction: "none" }}
      >
        <ambientLight intensity={0.55} />
        <directionalLight position={[5, 4, 5]} intensity={0.35} />
        <SceneRoot {...props} />
      </Canvas>
    </div>
  );
}

// ── SceneRoot — owns the intro animation ────────────────────────────────── //

function SceneRoot({
  highlightedCityId,
  confirmedCityId,
  onMarkerClick,
  skipIntroAnimation,
  onIntroComplete,
}: WorldMapProps) {
  const { camera } = useThree();
  const continentRef = useRef<THREE.LineSegments>(null);
  const introStartRef = useRef<number>(0);
  const introCompletedRef = useRef<boolean>(skipIntroAnimation);
  const [introActive, setIntroActive] = useState<boolean>(!skipIntroAnimation);

  const onIntroCompleteRef = useRef(onIntroComplete);
  useEffect(() => {
    onIntroCompleteRef.current = onIntroComplete;
  }, [onIntroComplete]);

  useEffect(() => {
    if (skipIntroAnimation) {
      camera.position.set(0, 0, Z_NEAR);
      onIntroCompleteRef.current?.();
      return;
    }
    introStartRef.current = performance.now() + BLANK_DELAY_MS;
    if (continentRef.current) {
      continentRef.current.geometry.setDrawRange(0, 0);
    }
  }, [skipIntroAnimation, camera]);

  useFrame(() => {
    if (skipIntroAnimation) return;
    if (introCompletedRef.current) return;
    const elapsed = performance.now() - introStartRef.current;
    if (elapsed < 0) return;
    const t = Math.min(1, elapsed / INTRO_TOTAL_MS);
    const ease = easeInOutCubic(t);

    camera.position.setZ(Z_FAR + (Z_NEAR - Z_FAR) * ease);

    if (continentRef.current) {
      const totalVerts = continentResult.segmentCount * 2;
      continentRef.current.geometry.setDrawRange(0, Math.floor(totalVerts * t));
    }

    if (t >= 1) {
      introCompletedRef.current = true;
      setIntroActive(false);
      // Wait for markers stagger to settle, then notify the parent.
      const markersDur = (CITIES.length - 1) * MARKER_STAGGER_MS + MARKER_FADE_MS;
      window.setTimeout(() => {
        onIntroCompleteRef.current?.();
      }, markersDur);
    }
  });

  return (
    <>
      <Globe continentRef={continentRef} />
      <Markers
        highlightedCityId={highlightedCityId}
        confirmedCityId={confirmedCityId}
        onMarkerClick={onMarkerClick}
        revealed={!introActive}
      />
      {!introActive && (
        <OrbitControls
          enableZoom
          enablePan={false}
          minDistance={Z_MIN}
          maxDistance={Z_MAX}
          enableDamping
          dampingFactor={0.08}
          rotateSpeed={0.5}
          zoomSpeed={0.6}
        />
      )}
    </>
  );
}

// ── Globe ───────────────────────────────────────────────────────────────── //

function Globe({ continentRef }: { continentRef: RefObject<THREE.LineSegments | null> }) {
  return (
    <group>
      {/* Ocean sphere */}
      <mesh>
        <sphereGeometry args={[GLOBE_RADIUS, 96, 96]} />
        <meshBasicMaterial color="#f0f0f0" />
      </mesh>

      {/* Subtle global graticule */}
      <lineSegments geometry={graticuleGeometry}>
        <lineBasicMaterial color="#000000" transparent opacity={0.06} />
      </lineSegments>

      {/* Continent-clipped hatching (interlaced lines inside terrain) */}
      <lineSegments geometry={hatchGeometry}>
        <lineBasicMaterial color="#000000" transparent opacity={0.18} />
      </lineSegments>

      {/* Continent outlines — animated via setDrawRange */}
      <lineSegments ref={continentRef} geometry={continentResult.geometry}>
        <lineBasicMaterial color="#000000" transparent opacity={0.95} />
      </lineSegments>
    </group>
  );
}

// ── Markers ─────────────────────────────────────────────────────────────── //

function Markers({
  highlightedCityId,
  confirmedCityId,
  onMarkerClick,
  revealed,
}: {
  highlightedCityId: string | null;
  confirmedCityId: string | null;
  onMarkerClick: (city: City) => void;
  revealed: boolean;
}) {
  const [hoveredCityId, setHoveredCityId] = useState<string | null>(null);
  const [pulseSerial, setPulseSerial] = useState<Record<string, number>>({});

  return (
    <group>
      {CITIES.map((city, i) => {
        const pos = latLonToVec3(city.lat, city.lon, GLOBE_RADIUS * 1.005);
        const isConfirmed = confirmedCityId === city.id;
        const isHighlighted = highlightedCityId === city.id;
        const isHovered = hoveredCityId === city.id;
        const state: "default" | "hover" | "selected" = isConfirmed
          ? "selected"
          : isHovered || isHighlighted
            ? "hover"
            : "default";
        const staggerMs = i * MARKER_STAGGER_MS;
        return (
          <CityMarker
            key={city.id}
            city={city}
            position={pos}
            state={state}
            revealed={revealed}
            staggerMs={staggerMs}
            pulseKey={pulseSerial[city.id] ?? 0}
            onPointerOver={() => {
              setHoveredCityId(city.id);
              setPulseSerial((s) => ({ ...s, [city.id]: (s[city.id] ?? 0) + 1 }));
              document.body.style.cursor = "pointer";
            }}
            onPointerOut={() => {
              setHoveredCityId((cur) => (cur === city.id ? null : cur));
              document.body.style.cursor = "";
            }}
            onClick={() => onMarkerClick(city)}
          />
        );
      })}
    </group>
  );
}

// ── CityMarker ──────────────────────────────────────────────────────────── //

function CityMarker({
  city,
  position,
  state,
  revealed,
  staggerMs,
  pulseKey,
  onPointerOver,
  onPointerOut,
  onClick,
}: {
  city: City;
  position: THREE.Vector3;
  state: "default" | "hover" | "selected";
  revealed: boolean;
  staggerMs: number;
  pulseKey: number;
  onPointerOver: () => void;
  onPointerOut: () => void;
  onClick: () => void;
}) {
  const [revealStarted, setRevealStarted] = useState<boolean>(revealed);

  // Stagger the per-marker reveal once `revealed` flips true.
  useEffect(() => {
    if (!revealed) return;
    const t = window.setTimeout(() => setRevealStarted(true), staggerMs);
    return () => window.clearTimeout(t);
  }, [revealed, staggerMs]);

  const opacity = revealStarted ? 1 : 0;

  return (
    <group position={[position.x, position.y, position.z]} visible={revealStarted}>
      {/* Hover pulse — one-shot ring; key change re-triggers the keyframe */}
      {state === "hover" && (
        <Html
          key={`pulse-${pulseKey}`}
          center
          zIndexRange={[5, 0]}
          style={{ pointerEvents: "none", opacity }}
        >
          <span
            style={{
              display: "block",
              width: 14,
              height: 14,
              borderRadius: "50%",
              border: "1px solid #000",
              animation: `locMarkerPulse ${PULSE_RING_MS}ms ${APPLE_EASE_CSS} 1`,
              transformOrigin: "center",
            }}
          />
        </Html>
      )}

      {state === "selected" ? (
        <>
          {/* Crosshair ring — flat ring oriented along the surface tangent */}
          <SurfaceRing
            innerRadius={MARKER_SELECTED_RING_INNER}
            outerRadius={MARKER_SELECTED_RING_OUTER}
            position={position}
          />
          {/* Center dot */}
          <mesh>
            <sphereGeometry args={[MARKER_SELECTED_DOT_R, 16, 16]} />
            <meshBasicMaterial color="#000000" />
          </mesh>
        </>
      ) : (
        <mesh>
          <sphereGeometry
            args={[state === "hover" ? MARKER_HOVER_R : MARKER_DEFAULT_R, 16, 16]}
          />
          <meshBasicMaterial color="#000000" />
        </mesh>
      )}

      {/* Generous invisible hit target */}
      <mesh
        onPointerOver={onPointerOver}
        onPointerOut={onPointerOut}
        onClick={(e) => {
          e.stopPropagation();
          onClick();
        }}
      >
        <sphereGeometry args={[MARKER_HIT_R, 12, 12]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      {/* HTML label, projected to 2D — small-caps typography */}
      <Html
        center={false}
        zIndexRange={[10, 0]}
        style={{
          pointerEvents: "none",
          opacity,
          transition: `opacity ${MARKER_FADE_MS}ms ${APPLE_EASE_CSS}`,
        }}
      >
        <span
          style={{
            display: "inline-block",
            transform: "translate(10px, -50%)",
            fontSize: 10,
            fontVariant: "small-caps",
            letterSpacing: "0.05em",
            fontWeight: state === "default" ? 500 : 700,
            color: "#000",
            whiteSpace: "nowrap",
            transition: `font-weight 160ms ${APPLE_EASE_CSS}`,
          }}
        >
          {city.name}
        </span>
      </Html>

    </group>
  );
}

// ── SurfaceRing — flat ring oriented to lie tangent to the sphere surface ─ //

function SurfaceRing({
  innerRadius,
  outerRadius,
  position,
}: {
  innerRadius: number;
  outerRadius: number;
  position: THREE.Vector3;
}) {
  // Orient the ring so its normal points outward from the sphere center.
  const ref = useRef<THREE.Mesh>(null);
  useEffect(() => {
    if (!ref.current) return;
    const normal = position.clone().normalize();
    ref.current.lookAt(normal.multiplyScalar(10));
  }, [position]);
  return (
    <mesh ref={ref}>
      <ringGeometry args={[innerRadius, outerRadius, 48]} />
      <meshBasicMaterial color="#000000" side={THREE.DoubleSide} />
    </mesh>
  );
}
