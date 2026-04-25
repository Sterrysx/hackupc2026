/**
 * InteractiveSchematic — Phase 2.
 *
 * iPhone-style click-to-zoom on a minimalist 2D schematic of the printer,
 * with a glassmorphic data popover that fades in once the camera settles
 * and live status tinting (soft pulse) on any part that is currently in a
 * warning / critical state.
 *
 * Zoom math:
 *   For SVG viewBox W×H and a part bounding box (x, y, w, h), we want the
 *   part's centre (cx, cy) to land at a target screen point (Tx, Ty) at a
 *   chosen scale s. SVG `transform="translate(tx ty) scale(s)"` reads
 *   right-to-left, so a coord (px, py) lands at (s·px + tx, s·py + ty).
 *   Solving for the centre:
 *       tx = Tx − s·cx,   ty = Ty − s·cy
 *   When the popover is shown, Tx is biased left of canvas centre so the
 *   focused part doesn't sit underneath the card.
 *
 * Why setAttribute via ref:
 *   `<motion.g transform={motionValue}>` does NOT subscribe — `motion.g`
 *   only auto-projects shorthand props (x/y/scale) via CSS transforms,
 *   which on SVG mix viewBox units with CSS pixels in browser-inconsistent
 *   ways. Updating the SVG `transform` attribute imperatively guarantees
 *   correct viewBox-unit semantics with zero React re-renders per frame.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { animate, AnimatePresence, motion, useMotionValue } from "framer-motion";
import { ArrowLeft } from "lucide-react";
import { useTwin } from "@/store/twin";
import { Badge, statusLabel, statusToTone } from "@/components/ui/Badge";
import { HealthRing } from "@/components/HealthRing";
import { formatEta } from "@/lib/alerts";
import type {
  ComponentForecast,
  ComponentId,
  ComponentState,
  OperationalStatus,
} from "@/types/telemetry";

const VB_W = 1200;
const VB_H = 720;

/** Fraction of the smaller viewport dimension the focused part should occupy. */
const FILL_FRACTION = 0.50;
/** Don't zoom past this — keeps strokes from looking absurd on tiny parts. */
const MAX_SCALE = 4.5;
/** Never zoom out below 1× either. */
const MIN_SCALE = 1;

/** Where the focused part lands on screen as fractions of the viewBox. */
const FOCUS_X_FRACTION = 0.36; // pulled to the left so the popover has room
const FOCUS_Y_FRACTION = 0.50;

/** Apple's "ease out expo-ish" — used in iOS sheets, photo zoom, etc. */
const APPLE_EASE: [number, number, number, number] = [0.32, 0.72, 0, 1];
const ZOOM_DURATION = 0.7;
const FADE_DURATION = 0.45;
const POPOVER_DELAY = 0.42;

/* ── Stroke / fill palette — derived from white opacities ──────────────── */

const COL = {
  STROKE_BASE:    "rgba(255, 255, 255, 0.32)",
  STROKE_FAINT:   "rgba(255, 255, 255, 0.16)",
  STROKE_VFAINT:  "rgba(255, 255, 255, 0.08)",
  STROKE_ACTIVE:  "rgba(255, 255, 255, 0.92)",
  FILL_FAINT:     "rgba(255, 255, 255, 0.05)",
  FILL_VFAINT:    "rgba(255, 255, 255, 0.025)",
  TEXT_LABEL:     "rgba(255, 255, 255, 0.42)",
  TEXT_VFAINT:    "rgba(255, 255, 255, 0.18)",
};

/** Soft, low-saturation status colours — same family as the Phase 1 badges. */
const WARN_STROKE = "rgba(245, 195, 130, 0.92)"; // sand
const CRIT_STROKE = "rgba(255, 130, 105, 0.92)"; // coral
const WARN_TINT   = "rgb(245, 195, 130)";
const CRIT_TINT   = "rgb(255, 130, 105)";

function strokeFor(status: OperationalStatus, active: boolean): string {
  if (status === "FAILED" || status === "CRITICAL") return CRIT_STROKE;
  if (status === "DEGRADED") return WARN_STROKE;
  return active ? COL.STROKE_ACTIVE : COL.STROKE_BASE;
}

function tintFor(status: OperationalStatus): string | null {
  if (status === "FAILED" || status === "CRITICAL") return CRIT_TINT;
  if (status === "DEGRADED") return WARN_TINT;
  return null;
}

interface PartBox { x: number; y: number; w: number; h: number; }

interface SchematicPart {
  id: ComponentId;
  label: string;
  subsystem: "recoating" | "printhead" | "thermal";
  /** Rectangle the camera frames when this part is selected. */
  zoomBox: PartBox;
  /** One or more rects whose interior catches clicks. */
  hitRects: PartBox[];
  render: (active: boolean, status: OperationalStatus) => React.ReactNode;
}

/* ── Layout coordinates (single source of truth) ───────────────────────── */

const RAIL_Y  = 200;
const RAIL_X1 = 180;
const RAIL_X2 = 1010;

const CHASSIS = { x: 540, y: 250, w: 220, h: 72 };
const CHAMBER = { x: 290, y: 365, w: 620, h: 195 };

/* ── Parts ─────────────────────────────────────────────────────────────── */

const PARTS: SchematicPart[] = [
  {
    id: "recoater_blade",
    label: "Recoater Blade",
    subsystem: "recoating",
    zoomBox: { x: 410, y: 175, w: 110, h: 70 },
    hitRects: [{ x: 410, y: 175, w: 110, h: 70 }],
    render: (active, status) => {
      const s = strokeFor(status, active);
      return (
        <g>
          {/* Carriage body — now with substance */}
          <rect x={430} y={185} width={80} height={26} rx={3}
            fill={COL.FILL_FAINT} stroke={s} strokeWidth={1}
            vectorEffect="non-scaling-stroke" />
          {/* Inner bracket detail */}
          <line x1={448} y1={193} x2={492} y2={193}
            stroke={COL.STROKE_VFAINT} strokeWidth={0.8}
            vectorEffect="non-scaling-stroke" />
          {/* Spreading blade edge */}
          <line x1={425} y1={220} x2={515} y2={220}
            stroke={s} strokeWidth={1.5} strokeLinecap="round"
            vectorEffect="non-scaling-stroke" />
          {/* Powder trail trace */}
          <line x1={425} y1={224} x2={515} y2={224}
            stroke={COL.STROKE_VFAINT} strokeWidth={1} strokeDasharray="2 3"
            vectorEffect="non-scaling-stroke" />
        </g>
      );
    },
  },
  {
    id: "recoater_motor",
    label: "Recoater Motor",
    subsystem: "recoating",
    zoomBox: { x: 985, y: 158, w: 90, h: 92 },
    hitRects: [{ x: 985, y: 158, w: 90, h: 92 }],
    render: (active, status) => {
      const s = strokeFor(status, active);
      return (
        <g>
          {/* Connector cable on top */}
          <path d="M 1030 168 L 1030 178" stroke={COL.STROKE_FAINT} strokeWidth={1}
            vectorEffect="non-scaling-stroke" />
          <rect x={1024} y={163} width={12} height={6} rx={1}
            fill={COL.FILL_FAINT} stroke={COL.STROKE_FAINT} strokeWidth={0.8}
            vectorEffect="non-scaling-stroke" />
          {/* Connection to rail */}
          <line x1={1010} y1={200} x2={1000} y2={200}
            stroke={s} strokeWidth={1}
            vectorEffect="non-scaling-stroke" />
          {/* Motor housing — solid look */}
          <rect x={1000} y={180} width={60} height={50} rx={4}
            fill={COL.FILL_FAINT} stroke={s} strokeWidth={1}
            vectorEffect="non-scaling-stroke" />
          {/* Stator coil */}
          <circle cx={1030} cy={205} r={14}
            fill="none" stroke={s} strokeWidth={1}
            vectorEffect="non-scaling-stroke" />
          {/* Rotor hub */}
          <circle cx={1030} cy={205} r={3.5}
            fill={s} stroke="none"
            vectorEffect="non-scaling-stroke" />
        </g>
      );
    },
  },
  {
    id: "thermal_resistor",
    label: "Thermal Firing Resistors",
    subsystem: "printhead",
    zoomBox: { x: 540, y: 248, w: 220, h: 50 },
    hitRects: [{ x: 540, y: 248, w: 220, h: 50 }],
    render: (active, status) => {
      const s = strokeFor(status, active);
      return (
        <g>
          {Array.from({ length: 10 }).map((_, i) => (
            <line
              key={i}
              x1={555 + i * 22}
              y1={258}
              x2={555 + i * 22}
              y2={290}
              stroke={s}
              strokeWidth={1}
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </g>
      );
    },
  },
  {
    id: "nozzle_plate",
    label: "Nozzle Plate",
    subsystem: "printhead",
    zoomBox: { x: 540, y: 305, w: 220, h: 38 },
    hitRects: [{ x: 540, y: 305, w: 220, h: 38 }],
    render: (active, status) => {
      const s = strokeFor(status, active);
      return (
        <g>
          {/* Bottom face line */}
          <line x1={545} y1={320} x2={755} y2={320}
            stroke={s} strokeWidth={1.5} strokeLinecap="round"
            vectorEffect="non-scaling-stroke" />
          {/* Nozzle dots */}
          {Array.from({ length: 32 }).map((_, i) => (
            <circle
              key={i}
              cx={550 + i * 6.5}
              cy={328}
              r={1}
              fill={s}
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </g>
      );
    },
  },
  {
    id: "heating_element",
    label: "Heating Element",
    subsystem: "thermal",
    zoomBox: { x: 280, y: 562, w: 640, h: 44 },
    hitRects: [{ x: 280, y: 562, w: 640, h: 44 }],
    render: (active, status) => {
      const s = strokeFor(status, active);
      const segments = 22;
      const startX = 290;
      const endX = 910;
      const cy = 583;
      const amp = 9;
      const w = (endX - startX) / segments;
      let path = `M ${startX} ${cy}`;
      for (let i = 0; i < segments; i++) {
        const xMid = startX + (i + 0.5) * w;
        const yPeak = i % 2 === 0 ? cy - amp : cy + amp;
        const xEnd = startX + (i + 1) * w;
        path += ` L ${xMid} ${yPeak} L ${xEnd} ${cy}`;
      }
      return (
        <g>
          {/* Power lead (left) */}
          <line x1={278} y1={cy} x2={290} y2={cy}
            stroke={s} strokeWidth={1}
            vectorEffect="non-scaling-stroke" />
          {/* Power lead (right) */}
          <line x1={910} y1={cy} x2={922} y2={cy}
            stroke={s} strokeWidth={1}
            vectorEffect="non-scaling-stroke" />
          {/* Coil */}
          <path d={path} fill="none" stroke={s} strokeWidth={1}
            strokeLinecap="round" strokeLinejoin="round"
            vectorEffect="non-scaling-stroke" />
        </g>
      );
    },
  },
  {
    id: "insulation_panel",
    label: "Insulation Panel",
    subsystem: "thermal",
    zoomBox: { x: 256, y: 348, w: 688, h: 270 },
    hitRects: [
      { x: 256, y: 348, w: 688, h: 22 },
      { x: 256, y: 596, w: 688, h: 22 },
      { x: 256, y: 348, w: 22,  h: 270 },
      { x: 922, y: 348, w: 22,  h: 270 },
    ],
    render: (active, status) => {
      const s = strokeFor(status, active);
      return (
        <g>
          {/* Outer dashed insulation perimeter */}
          <rect x={266} y={355} width={668} height={258} rx={4}
            fill="none" stroke={s} strokeWidth={1} strokeDasharray="4 4"
            vectorEffect="non-scaling-stroke" />
          {/* Side hatch ticks (insulation cross-section markers) */}
          {[0, 1, 2, 3, 4].map((i) => {
            const yy = 380 + i * 50;
            return (
              <g key={i}>
                <line x1={268} y1={yy} x2={278} y2={yy + 6}
                  stroke={s} strokeWidth={0.8}
                  vectorEffect="non-scaling-stroke" />
                <line x1={922} y1={yy} x2={932} y2={yy + 6}
                  stroke={s} strokeWidth={0.8}
                  vectorEffect="non-scaling-stroke" />
              </g>
            );
          })}
        </g>
      );
    },
  },
];

/* ── Camera math ───────────────────────────────────────────────────────── */

interface CameraState { x: number; y: number; scale: number; }

function cameraFor(box: PartBox | null): CameraState {
  if (!box) return { x: 0, y: 0, scale: 1 };
  const rawScale = Math.min(
    (VB_W * FILL_FRACTION) / box.w,
    (VB_H * FILL_FRACTION) / box.h,
  );
  const scale = Math.max(MIN_SCALE, Math.min(rawScale, MAX_SCALE));
  const cx = box.x + box.w / 2;
  const cy = box.y + box.h / 2;
  return {
    x: VB_W * FOCUS_X_FRACTION - scale * cx,
    y: VB_H * FOCUS_Y_FRACTION - scale * cy,
    scale,
  };
}

/* ── Static decoration ─────────────────────────────────────────────────── */

function StaticDecoration() {
  return (
    <g pointerEvents="none">
      {/* Outer machine frame */}
      <rect x={80} y={80} width={1040} height={560} rx={20}
        fill={COL.FILL_VFAINT} stroke={COL.STROKE_FAINT} strokeWidth={1}
        vectorEffect="non-scaling-stroke" />

      {/* Title block */}
      <line x1={100} y1={622} x2={360} y2={622}
        stroke={COL.STROKE_VFAINT} strokeWidth={1}
        vectorEffect="non-scaling-stroke" />
      <text x={100} y={614} fill={COL.TEXT_LABEL}
        fontSize={9} letterSpacing="0.18em" fontFamily="var(--font-mono)">
        HP METAL JET S100 · DIGITAL TWIN
      </text>
      <text x={100} y={636} fill={COL.TEXT_VFAINT}
        fontSize={8} letterSpacing="0.18em" fontFamily="var(--font-mono)">
        2D INTERACTIVE SCHEMATIC · v0.1
      </text>

      {/* Subsystem captions */}
      <text x={600} y={148} fill={COL.TEXT_LABEL} fontSize={9}
        letterSpacing="0.22em" textAnchor="middle" fontFamily="var(--font-mono)">
        RECOATING SYSTEM
      </text>
      <text x={650} y={232} fill={COL.TEXT_LABEL} fontSize={9}
        letterSpacing="0.22em" textAnchor="middle" fontFamily="var(--font-mono)">
        PRINTHEAD ARRAY
      </text>
      <text x={600} y={678} fill={COL.TEXT_LABEL} fontSize={9}
        letterSpacing="0.22em" textAnchor="middle" fontFamily="var(--font-mono)">
        THERMAL CONTROL
      </text>

      {/* Recoater motion rail with end-stops */}
      <line x1={RAIL_X1} y1={RAIL_Y} x2={RAIL_X2} y2={RAIL_Y}
        stroke={COL.STROKE_BASE} strokeWidth={1} strokeLinecap="round"
        vectorEffect="non-scaling-stroke" />
      <line x1={RAIL_X1} y1={RAIL_Y - 6} x2={RAIL_X1} y2={RAIL_Y + 6}
        stroke={COL.STROKE_BASE} strokeWidth={1}
        vectorEffect="non-scaling-stroke" />
      {/* Right-side limit switch — small filled square indicator */}
      <rect x={1006} y={RAIL_Y - 4} width={8} height={8} rx={1}
        fill={COL.STROKE_FAINT} stroke="none"
        vectorEffect="non-scaling-stroke" />

      {/* Binder feed line — soft dashed curve from frame top into chassis */}
      <path d={`M 650 100 Q 650 175 650 ${CHASSIS.y}`}
        fill="none" stroke={COL.STROKE_VFAINT} strokeWidth={1} strokeDasharray="3 5"
        vectorEffect="non-scaling-stroke" />
      <circle cx={650} cy={100} r={2.5}
        fill="none" stroke={COL.STROKE_FAINT} strokeWidth={1}
        vectorEffect="non-scaling-stroke" />

      {/* Printhead chassis — solid feel via soft fill + corner mounting holes */}
      <rect x={CHASSIS.x} y={CHASSIS.y} width={CHASSIS.w} height={CHASSIS.h} rx={4}
        fill={COL.FILL_FAINT} stroke={COL.STROKE_FAINT} strokeWidth={1}
        vectorEffect="non-scaling-stroke" />
      {[
        [CHASSIS.x + 6, CHASSIS.y + 6],
        [CHASSIS.x + CHASSIS.w - 6, CHASSIS.y + 6],
        [CHASSIS.x + 6, CHASSIS.y + CHASSIS.h - 6],
        [CHASSIS.x + CHASSIS.w - 6, CHASSIS.y + CHASSIS.h - 6],
      ].map(([cx, cy], i) => (
        <circle key={i} cx={cx} cy={cy} r={1.5}
          fill="none" stroke={COL.STROKE_VFAINT} strokeWidth={0.8}
          vectorEffect="non-scaling-stroke" />
      ))}
      {/* Suspension lines from rail to printhead */}
      <line x1={580} y1={210} x2={580} y2={250}
        stroke={COL.STROKE_VFAINT} strokeWidth={1}
        vectorEffect="non-scaling-stroke" />
      <line x1={720} y1={210} x2={720} y2={250}
        stroke={COL.STROKE_VFAINT} strokeWidth={1}
        vectorEffect="non-scaling-stroke" />

      {/* Build chamber walls + powder bed surface */}
      <rect x={CHAMBER.x} y={CHAMBER.y} width={CHAMBER.w} height={CHAMBER.h} rx={2}
        fill={COL.FILL_FAINT} stroke={COL.STROKE_BASE} strokeWidth={1}
        vectorEffect="non-scaling-stroke" />
      <line x1={300} y1={420} x2={900} y2={420}
        stroke={COL.STROKE_FAINT} strokeWidth={1} strokeDasharray="3 4"
        vectorEffect="non-scaling-stroke" />
      <text x={600} y={395} fill={COL.STROKE_FAINT} fontSize={8}
        letterSpacing="0.18em" textAnchor="middle" fontFamily="var(--font-mono)">
        BUILD CHAMBER
      </text>

      {/* Powder bed texture (subtle stipple) */}
      {(() => {
        const dots: React.ReactElement[] = [];
        const cols = 18;
        for (let row = 0; row < 5; row++) {
          for (let col = 0; col < cols; col++) {
            const x = 320 + col * 32 + (row % 2) * 16;
            const y = 442 + row * 22;
            if (x > 880 || y > 540) continue;
            dots.push(
              <circle key={`${row}-${col}`} cx={x} cy={y} r={0.7}
                fill={COL.STROKE_VFAINT} vectorEffect="non-scaling-stroke" />,
            );
          }
        }
        return dots;
      })()}
    </g>
  );
}

/* ── Component ─────────────────────────────────────────────────────────── */

export function InteractiveSchematic() {
  const snapshot = useTwin((s) => s.snapshot);
  const [selectedId, setSelectedId] = useState<ComponentId | null>(null);

  // Look up live status per part — drives stroke colour + warning pulse.
  const statusMap = useMemo<Record<ComponentId, OperationalStatus>>(() => {
    const m = {} as Record<ComponentId, OperationalStatus>;
    for (const c of snapshot.components) m[c.id] = c.status;
    return m;
  }, [snapshot.components]);

  // Camera state lives in motion values; the SVG transform attribute is
  // updated imperatively via setAttribute so we get true viewBox-unit math
  // with zero React re-renders per animation frame.
  const groupRef = useRef<SVGGElement>(null);
  const tx = useMotionValue(0);
  const ty = useMotionValue(0);
  const ts = useMotionValue(1);

  useEffect(() => {
    const apply = () => {
      const g = groupRef.current;
      if (!g) return;
      g.setAttribute(
        "transform",
        `translate(${tx.get()} ${ty.get()}) scale(${ts.get()})`,
      );
    };
    apply();
    const u1 = tx.on("change", apply);
    const u2 = ty.on("change", apply);
    const u3 = ts.on("change", apply);
    return () => { u1(); u2(); u3(); };
  }, [tx, ty, ts]);

  useEffect(() => {
    const sel = PARTS.find((p) => p.id === selectedId) ?? null;
    const cam = cameraFor(sel?.zoomBox ?? null);
    const opts = { duration: ZOOM_DURATION, ease: APPLE_EASE };
    const a1 = animate(tx, cam.x, opts);
    const a2 = animate(ty, cam.y, opts);
    const a3 = animate(ts, cam.scale, opts);
    return () => { a1.stop(); a2.stop(); a3.stop(); };
  }, [selectedId, tx, ty, ts]);

  // Esc returns to overview.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && selectedId) setSelectedId(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedId]);

  const selected = PARTS.find((p) => p.id === selectedId) ?? null;
  const selectedComponent = selected
    ? snapshot.components.find((c) => c.id === selected.id)
    : null;
  const selectedForecast = selected
    ? snapshot.forecasts.find((f) => f.id === selected.id)
    : null;

  return (
    <div className="relative w-full h-full">
      {/* Back-to-overview pill */}
      <AnimatePresence>
        {selected && (
          <motion.button
            key="back"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.32, ease: APPLE_EASE }}
            onClick={() => setSelectedId(null)}
            className="absolute top-6 left-6 z-10 inline-flex items-center gap-2 h-10 pl-3 pr-4 rounded-full glass-floating text-[13px] text-[var(--color-fg)] hover:bg-[oklch(0.30_0.003_260/0.85)] transition-colors"
          >
            <ArrowLeft size={14} />
            <span>Back to overview</span>
          </motion.button>
        )}
      </AnimatePresence>

      {/* Selected-part caption */}
      <AnimatePresence>
        {selected && (
          <motion.div
            key={`cap-${selected.id}`}
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.4, delay: 0.18, ease: APPLE_EASE }}
            className="absolute top-7 left-1/2 -translate-x-1/2 z-10 text-[10.5px] uppercase tracking-[0.22em] text-[var(--color-fg-muted)] pointer-events-none"
          >
            {selected.label}
          </motion.div>
        )}
      </AnimatePresence>

      {/* The canvas */}
      <svg
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        preserveAspectRatio="xMidYMid meet"
        className="w-full h-full select-none"
        onClick={() => setSelectedId(null)}
        role="img"
        aria-label="HP Metal Jet S100 schematic"
      >
        {/* The transform is set imperatively in useEffect — never declared in JSX. */}
        <g ref={groupRef}>
          <StaticDecoration />

          <g id="recoating-system">
            {PARTS.filter((p) => p.subsystem === "recoating").map((p) => (
              <Part key={p.id} part={p} status={statusMap[p.id]} selectedId={selectedId} onSelect={setSelectedId} />
            ))}
          </g>
          <g id="printhead-array">
            {PARTS.filter((p) => p.subsystem === "printhead").map((p) => (
              <Part key={p.id} part={p} status={statusMap[p.id]} selectedId={selectedId} onSelect={setSelectedId} />
            ))}
          </g>
          <g id="thermal-control">
            {PARTS.filter((p) => p.subsystem === "thermal").map((p) => (
              <Part key={p.id} part={p} status={statusMap[p.id]} selectedId={selectedId} onSelect={setSelectedId} />
            ))}
          </g>
        </g>
      </svg>

      {/* Floating data popover (right side, after zoom settles) */}
      <AnimatePresence>
        {selected && selectedComponent && selectedForecast && (
          <PopoverCard
            key={`popover-${selected.id}`}
            component={selectedComponent}
            forecast={selectedForecast}
            forecastHorizonMin={snapshot.forecastHorizonMin}
          />
        )}
      </AnimatePresence>

      {/* Persistent footer hint */}
      <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-10 text-[11px] text-[var(--color-fg-faint)] tracking-tight pointer-events-none">
        {selected
          ? "Click anywhere or press Esc to return"
          : "Click any component to zoom in"}
      </div>
    </div>
  );
}

/* ── Per-part wrapper: dim, click, hit areas, warning halo ─────────────── */

function Part({
  part,
  status,
  selectedId,
  onSelect,
}: {
  part: SchematicPart;
  status: OperationalStatus;
  selectedId: ComponentId | null;
  onSelect: (id: ComponentId | null) => void;
}) {
  const active = selectedId === part.id;
  const faded = selectedId !== null && !active;
  const tint = tintFor(status);
  return (
    <motion.g
      id={part.id}
      data-part={part.id}
      animate={{ opacity: faded ? 0.18 : 1 }}
      transition={{ duration: FADE_DURATION, ease: APPLE_EASE }}
      style={{ cursor: "pointer" }}
      onClick={(e) => {
        e.stopPropagation();
        onSelect(active ? null : part.id);
      }}
    >
      {/* Soft pulsing tint behind warning / critical parts */}
      {tint && (
        <rect
          x={part.zoomBox.x - 4}
          y={part.zoomBox.y - 4}
          width={part.zoomBox.w + 8}
          height={part.zoomBox.h + 8}
          rx={8}
          fill={tint}
          style={{ animation: "statusPulse 3s ease-in-out infinite" }}
          pointerEvents="none"
        />
      )}
      {part.render(active, status)}
      {part.hitRects.map((r, i) => (
        <rect
          key={i}
          x={r.x}
          y={r.y}
          width={r.w}
          height={r.h}
          fill="transparent"
          pointerEvents="all"
        />
      ))}
    </motion.g>
  );
}

/* ── Glassmorphic data popover ─────────────────────────────────────────── */

function PopoverCard({
  component,
  forecast,
  forecastHorizonMin,
}: {
  component: ComponentState;
  forecast: ComponentForecast;
  forecastHorizonMin: number;
}) {
  const tone = statusToTone(component.status);
  const primaryMetrics = component.metrics.slice(0, 3);

  return (
    <motion.div
      initial={{ opacity: 0, x: 18, scale: 0.98 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: 14, scale: 0.98 }}
      transition={{ duration: 0.45, delay: POPOVER_DELAY, ease: APPLE_EASE }}
      onClick={(e) => e.stopPropagation()}
      className="absolute top-1/2 right-6 z-20 w-[340px] -translate-y-1/2 rounded-3xl glass-floating p-7"
    >
      {/* Header */}
      <header className="flex items-start justify-between gap-4 mb-6">
        <div className="min-w-0">
          <p className="text-[10px] uppercase tracking-[0.20em] text-[var(--color-fg-faint)] mb-1.5">
            {prettySubsystem(component.subsystem)}
          </p>
          <h3 className="text-[19px] font-medium tracking-tight text-[var(--color-fg)] leading-tight">
            {component.label}
          </h3>
          <div className="mt-2.5">
            <Badge tone={tone} size="sm" withDot>
              {statusLabel(component.status)}
            </Badge>
          </div>
        </div>
        <HealthRing
          value={component.healthIndex}
          predicted={forecast.predictedHealthIndex}
          size={64}
          thickness={4}
          showValue
        />
      </header>

      {/* Live metrics */}
      <div>
        <p className="text-[10px] uppercase tracking-[0.18em] text-[var(--color-fg-faint)] mb-2.5">
          Live metrics
        </p>
        <dl className="flex flex-col">
          {primaryMetrics.map((m, i) => (
            <div
              key={m.key}
              className={`flex items-baseline justify-between py-2.5 ${i !== 0 ? "border-t border-[var(--color-border)]" : ""}`}
            >
              <dt className="text-[12.5px] text-[var(--color-fg-muted)]">{m.label}</dt>
              <dd className="text-[13.5px] font-medium tabular-nums text-[var(--color-fg)]">
                {formatValue(m.value)}
                {m.unit && <span className="text-[var(--color-fg-faint)]"> {m.unit}</span>}
              </dd>
            </div>
          ))}
        </dl>
      </div>

      {/* Predictive forecast */}
      <section className="mt-6 pt-6 border-t border-[var(--color-border)]">
        <header className="flex items-center justify-between mb-3">
          <span className="text-[10px] uppercase tracking-[0.18em] text-[var(--color-fg-faint)]">
            Forecast · {forecastHorizonMin} min
          </span>
          <span className="text-[10.5px] tabular-nums text-[var(--color-fg-faint)]">
            {(forecast.confidence * 100).toFixed(0)}% conf
          </span>
        </header>

        {(forecast.minutesUntilCritical !== null || forecast.minutesUntilFailure !== null) && (
          <div className="flex flex-wrap gap-1.5 mb-3">
            {forecast.minutesUntilFailure !== null && (
              <Badge tone="crit" size="sm">
                Failure ~{formatEta(forecast.minutesUntilFailure)}
              </Badge>
            )}
            {forecast.minutesUntilCritical !== null && (
              <Badge tone="warn" size="sm">
                Critical ~{formatEta(forecast.minutesUntilCritical)}
              </Badge>
            )}
          </div>
        )}

        <p className="text-[12.5px] text-[var(--color-fg-muted)] leading-relaxed">
          {forecast.rationale}
        </p>
      </section>
    </motion.div>
  );
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

function prettySubsystem(s: ComponentState["subsystem"]): string {
  switch (s) {
    case "recoating": return "Recoating system";
    case "printhead": return "Printhead array";
    case "thermal":   return "Thermal control";
  }
}

function formatValue(v: number): string {
  if (Number.isInteger(v)) return v.toString();
  if (Math.abs(v) >= 100) return v.toFixed(1);
  return v.toFixed(2);
}
