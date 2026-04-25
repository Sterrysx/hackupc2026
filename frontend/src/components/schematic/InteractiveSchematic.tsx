/**
 * InteractiveSchematic — Phase 2.5 (unified-layout edition).
 *
 * Spring-physics zoom on a minimalist 2D schematic of the printer. Selection
 * lives in the global store so the right-hand sidebar can react instantly
 * (focus mode shows deep diagnostics for the picked part). The popover from
 * the previous iteration is gone — the sidebar replaces it.
 *
 * Zoom math:
 *   For SVG viewBox W×H and a part box (x, y, w, h), we want the part centre
 *   (cx, cy) to land at the centre of the canvas at scale s. SVG transform
 *   "translate(tx ty) scale(s)" reads right-to-left, so a coord (px, py)
 *   lands at (s·px + tx, s·py + ty). Solve:
 *       tx = W/2 − s·cx,   ty = H/2 − s·cy
 *
 * Why setAttribute via ref:
 *   `motion.g transform={motionValue}` doesn't subscribe — `motion.g` only
 *   auto-projects shorthand transforms (x/y/scale) via CSS, which on SVG
 *   conflate viewBox units with CSS pixels in browser-inconsistent ways.
 *   Writing the SVG `transform` attribute imperatively guarantees clean
 *   viewBox-unit semantics with zero React re-renders per frame.
 */

import { useEffect, useMemo, useRef } from "react";
import { animate, motion, useMotionValue } from "framer-motion";
import { useTwin } from "@/store/twin";
import type { ComponentId, OperationalStatus } from "@/types/telemetry";

const VB_W = 1200;
const VB_H = 720;

const FILL_FRACTION = 0.55;
const MAX_SCALE = 4.5;
const MIN_SCALE = 1;

/** Spring config — high stiffness, near-critical damping. Heavy + deliberate. */
const ZOOM_SPRING = {
  type: "spring" as const,
  stiffness: 100,
  damping: 22,
  mass: 1,
};

/** Default ease for everything that's not the zoom — Apple's ease-out-expo. */
const APPLE_EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];
const FADE_DURATION = 0.45;

/* ── Stroke / fill palette ─────────────────────────────────────────────── */

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

const WARN_STROKE = "rgba(245, 195, 130, 0.92)";
const CRIT_STROKE = "rgba(255, 130, 105, 0.92)";
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
  zoomBox: PartBox;
  hitRects: PartBox[];
  render: (active: boolean, status: OperationalStatus) => React.ReactNode;
}

/* ── Layout coordinates ────────────────────────────────────────────────── */

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
          <rect x={430} y={185} width={80} height={26} rx={3}
            fill={COL.FILL_FAINT} stroke={s} strokeWidth={1}
            vectorEffect="non-scaling-stroke" />
          <line x1={448} y1={193} x2={492} y2={193}
            stroke={COL.STROKE_VFAINT} strokeWidth={0.8}
            vectorEffect="non-scaling-stroke" />
          <line x1={425} y1={220} x2={515} y2={220}
            stroke={s} strokeWidth={1.5} strokeLinecap="round"
            vectorEffect="non-scaling-stroke" />
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
          <path d="M 1030 168 L 1030 178" stroke={COL.STROKE_FAINT} strokeWidth={1}
            vectorEffect="non-scaling-stroke" />
          <rect x={1024} y={163} width={12} height={6} rx={1}
            fill={COL.FILL_FAINT} stroke={COL.STROKE_FAINT} strokeWidth={0.8}
            vectorEffect="non-scaling-stroke" />
          <line x1={1010} y1={200} x2={1000} y2={200}
            stroke={s} strokeWidth={1}
            vectorEffect="non-scaling-stroke" />
          <rect x={1000} y={180} width={60} height={50} rx={4}
            fill={COL.FILL_FAINT} stroke={s} strokeWidth={1}
            vectorEffect="non-scaling-stroke" />
          <circle cx={1030} cy={205} r={14}
            fill="none" stroke={s} strokeWidth={1}
            vectorEffect="non-scaling-stroke" />
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
            <line key={i}
              x1={555 + i * 22} y1={258}
              x2={555 + i * 22} y2={290}
              stroke={s} strokeWidth={1} strokeLinecap="round"
              vectorEffect="non-scaling-stroke" />
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
          <line x1={545} y1={320} x2={755} y2={320}
            stroke={s} strokeWidth={1.5} strokeLinecap="round"
            vectorEffect="non-scaling-stroke" />
          {Array.from({ length: 32 }).map((_, i) => (
            <circle key={i} cx={550 + i * 6.5} cy={328} r={1}
              fill={s} vectorEffect="non-scaling-stroke" />
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
      const startX = 290, endX = 910, cy = 583, amp = 9;
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
          <line x1={278} y1={cy} x2={290} y2={cy}
            stroke={s} strokeWidth={1} vectorEffect="non-scaling-stroke" />
          <line x1={910} y1={cy} x2={922} y2={cy}
            stroke={s} strokeWidth={1} vectorEffect="non-scaling-stroke" />
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
          <rect x={266} y={355} width={668} height={258} rx={4}
            fill="none" stroke={s} strokeWidth={1} strokeDasharray="4 4"
            vectorEffect="non-scaling-stroke" />
          {[0, 1, 2, 3, 4].map((i) => {
            const yy = 380 + i * 50;
            return (
              <g key={i}>
                <line x1={268} y1={yy} x2={278} y2={yy + 6}
                  stroke={s} strokeWidth={0.8} vectorEffect="non-scaling-stroke" />
                <line x1={922} y1={yy} x2={932} y2={yy + 6}
                  stroke={s} strokeWidth={0.8} vectorEffect="non-scaling-stroke" />
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
    x: VB_W / 2 - scale * cx,
    y: VB_H / 2 - scale * cy,
    scale,
  };
}

/* ── Static decoration ─────────────────────────────────────────────────── */

function StaticDecoration() {
  return (
    <g pointerEvents="none">
      <rect x={80} y={80} width={1040} height={560} rx={20}
        fill={COL.FILL_VFAINT} stroke={COL.STROKE_FAINT} strokeWidth={1}
        vectorEffect="non-scaling-stroke" />

      <line x1={100} y1={622} x2={360} y2={622}
        stroke={COL.STROKE_VFAINT} strokeWidth={1} vectorEffect="non-scaling-stroke" />
      <text x={100} y={614} fill={COL.TEXT_LABEL}
        fontSize={9} letterSpacing="0.18em" fontFamily="var(--font-mono)">
        HP METAL JET S100 · DIGITAL TWIN
      </text>
      <text x={100} y={636} fill={COL.TEXT_VFAINT}
        fontSize={8} letterSpacing="0.18em" fontFamily="var(--font-mono)">
        2D INTERACTIVE SCHEMATIC · v0.2
      </text>

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

      <line x1={RAIL_X1} y1={RAIL_Y} x2={RAIL_X2} y2={RAIL_Y}
        stroke={COL.STROKE_BASE} strokeWidth={1} strokeLinecap="round"
        vectorEffect="non-scaling-stroke" />
      <line x1={RAIL_X1} y1={RAIL_Y - 6} x2={RAIL_X1} y2={RAIL_Y + 6}
        stroke={COL.STROKE_BASE} strokeWidth={1} vectorEffect="non-scaling-stroke" />
      <rect x={1006} y={RAIL_Y - 4} width={8} height={8} rx={1}
        fill={COL.STROKE_FAINT} stroke="none" vectorEffect="non-scaling-stroke" />

      <path d={`M 650 100 Q 650 175 650 ${CHASSIS.y}`}
        fill="none" stroke={COL.STROKE_VFAINT} strokeWidth={1} strokeDasharray="3 5"
        vectorEffect="non-scaling-stroke" />
      <circle cx={650} cy={100} r={2.5}
        fill="none" stroke={COL.STROKE_FAINT} strokeWidth={1}
        vectorEffect="non-scaling-stroke" />

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
      <line x1={580} y1={210} x2={580} y2={250}
        stroke={COL.STROKE_VFAINT} strokeWidth={1} vectorEffect="non-scaling-stroke" />
      <line x1={720} y1={210} x2={720} y2={250}
        stroke={COL.STROKE_VFAINT} strokeWidth={1} vectorEffect="non-scaling-stroke" />

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
  // Selection now lives in the global store so the sidebar reacts in real-time.
  const snapshot = useTwin((s) => s.snapshot);
  const selectedId = useTwin((s) => s.selectedComponentId);
  const setSelected = useTwin((s) => s.selectComponent);

  const statusMap = useMemo<Record<ComponentId, OperationalStatus>>(() => {
    const m = {} as Record<ComponentId, OperationalStatus>;
    for (const c of snapshot.components) m[c.id] = c.status;
    return m;
  }, [snapshot.components]);

  const groupRef = useRef<SVGGElement>(null);
  const tx = useMotionValue(0);
  const ty = useMotionValue(0);
  const ts = useMotionValue(1);

  // Imperative SVG transform attribute sync (zero React re-renders per frame).
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

  // Spring-driven camera tween on selection change.
  useEffect(() => {
    const sel = PARTS.find((p) => p.id === selectedId) ?? null;
    const cam = cameraFor(sel?.zoomBox ?? null);
    const a1 = animate(tx, cam.x, ZOOM_SPRING);
    const a2 = animate(ty, cam.y, ZOOM_SPRING);
    const a3 = animate(ts, cam.scale, ZOOM_SPRING);
    return () => { a1.stop(); a2.stop(); a3.stop(); };
  }, [selectedId, tx, ty, ts]);

  // Esc returns to overview.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && selectedId) setSelected(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedId, setSelected]);

  return (
    <div className="relative w-full h-full">
      <svg
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        preserveAspectRatio="xMidYMid meet"
        className="w-full h-full select-none"
        onClick={() => setSelected(null)}
        role="img"
        aria-label="HP Metal Jet S100 schematic"
      >
        {/* transform set imperatively in useEffect — never declared in JSX. */}
        <g ref={groupRef}>
          <StaticDecoration />

          <g id="recoating-system">
            {PARTS.filter((p) => p.subsystem === "recoating").map((p) => (
              <Part key={p.id} part={p} status={statusMap[p.id]} selectedId={selectedId} onSelect={setSelected} />
            ))}
          </g>
          <g id="printhead-array">
            {PARTS.filter((p) => p.subsystem === "printhead").map((p) => (
              <Part key={p.id} part={p} status={statusMap[p.id]} selectedId={selectedId} onSelect={setSelected} />
            ))}
          </g>
          <g id="thermal-control">
            {PARTS.filter((p) => p.subsystem === "thermal").map((p) => (
              <Part key={p.id} part={p} status={statusMap[p.id]} selectedId={selectedId} onSelect={setSelected} />
            ))}
          </g>
        </g>
      </svg>

    </div>
  );
}

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
        <rect key={i} x={r.x} y={r.y} width={r.w} height={r.h}
          fill="transparent" pointerEvents="all" />
      ))}
    </motion.g>
  );
}
