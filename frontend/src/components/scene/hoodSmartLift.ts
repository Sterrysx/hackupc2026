import type { ComponentId } from "@/types/telemetry";

/**
 * When any of these HP Metal Jet S100 subsystems are focused, the upper
 * charcoal hood occludes a clean view — we translate the hood (and
 * louvered top / exhaust) upward as a "smart lift" (Phase 3.11).
 */
export const HOOD_SMART_LIFT_COMPONENT_IDS: readonly ComponentId[] = [
  "recoater_motor",
  "recoater_blade",
  "nozzle_plate",
  "thermal_resistor",
];

export function isHoodSmartLiftTarget(id: ComponentId | null): boolean {
  if (!id) return false;
  return HOOD_SMART_LIFT_COMPONENT_IDS.includes(id);
}

/** Target vertical lift (meters) for the animated hood group. */
export const HOOD_SMART_LIFT_DELTA = 2.0;

/**
 * Damped lift height this frame, written by `MachineModel` and read by
 * `CameraRig` (useFrame priority after the hood) — no per-frame Zustand.
 */
export const hoodSmartLiftMeters = { current: 0 };
