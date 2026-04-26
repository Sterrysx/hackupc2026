import { useEffect, useRef } from "react";
import type { ComponentRef } from "react";
import { useThree } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import type { Camera } from "three";
import { MOUSE, TOUCH, Vector3 } from "three";
import { useTwin } from "@/store/twin";
import type { ComponentId } from "@/types/telemetry";
import {
  HOOD_SMART_LIFT_DELTA,
  hoodSmartLiftMeters,
  isHoodSmartLiftTarget,
} from "@/components/scene/hoodSmartLift";

const OVERVIEW_POS = new Vector3(7.5, 3.6, 8.5);
const OVERVIEW_LOOK_AT = new Vector3(-0.8, 1.7, 0);

/**
 * Strength of the focus zoom: 0 keeps the camera at overview, 1 jumps all
 * the way to the close-up pose. 0.6 = a calm two-step zoom that still frames
 * the assembly clearly without snapping into its face.
 */
const FOCUS_BLEND = 0.6;

/** Linear interpolation from the overview pose toward a close-up pose. */
function blendFromOverview(closeUp: Vector3, overview: Vector3, t: number): Vector3 {
  return overview.clone().lerp(closeUp, t);
}

const FOCUS: Partial<Record<ComponentId, { position: Vector3; lookAt: Vector3 }>> = {
  recoater_blade: {
    position: blendFromOverview(new Vector3(2.4, 4.4, 6.0), OVERVIEW_POS, FOCUS_BLEND),
    lookAt:   blendFromOverview(new Vector3(0.5, 1.6, 0),   OVERVIEW_LOOK_AT, FOCUS_BLEND),
  },
  recoater_motor: {
    position: blendFromOverview(new Vector3(2.7, 4.0, 5.6),    OVERVIEW_POS, FOCUS_BLEND),
    lookAt:   blendFromOverview(new Vector3(1.35, 1.5, 0.12),  OVERVIEW_LOOK_AT, FOCUS_BLEND),
  },
  nozzle_plate: {
    position: blendFromOverview(new Vector3(2.1, 3.5, 5.0),  OVERVIEW_POS, FOCUS_BLEND),
    lookAt:   blendFromOverview(new Vector3(0.5, 1.25, 0),   OVERVIEW_LOOK_AT, FOCUS_BLEND),
  },
  thermal_resistor: {
    position: blendFromOverview(new Vector3(2.1, 3.5, 5.0),  OVERVIEW_POS, FOCUS_BLEND),
    lookAt:   blendFromOverview(new Vector3(0.5, 1.25, 0),   OVERVIEW_LOOK_AT, FOCUS_BLEND),
  },
  heating_element: {
    position: blendFromOverview(new Vector3(2.5, 2.6, 5.4),  OVERVIEW_POS, FOCUS_BLEND),
    lookAt:   blendFromOverview(new Vector3(0.5, -0.1, 0),   OVERVIEW_LOOK_AT, FOCUS_BLEND),
  },
  insulation_panel: {
    position: blendFromOverview(new Vector3(2.5, 2.6, 5.4),  OVERVIEW_POS, FOCUS_BLEND),
    lookAt:   blendFromOverview(new Vector3(0.5, -0.1, 0),   OVERVIEW_LOOK_AT, FOCUS_BLEND),
  },
};

function applyPose(
  camera: Camera,
  controls: ComponentRef<typeof OrbitControls>,
  position: Vector3,
  lookAt: Vector3,
) {
  camera.position.copy(position);
  camera.lookAt(lookAt);
  controls.target.copy(lookAt);
  controls.update();
}

export function CameraRig() {
  const camera = useThree((s) => s.camera);
  const selectedId = useTwin((s) => s.selectedComponentId);
  const cameraOpen = useTwin((s) => s.cameraOpen);

  const controlsRef = useRef<ComponentRef<typeof OrbitControls> | null>(null);

  useEffect(() => {
    const ctrl = controlsRef.current;
    if (!ctrl) return;
    applyPose(camera, ctrl, OVERVIEW_POS, OVERVIEW_LOOK_AT);
  }, [camera]);

  useEffect(() => {
    const ctrl = controlsRef.current;
    if (!ctrl) return;

    // Default unfocused state: left-click rotates, **middle-click (scroll-
    // wheel button) drags-to-pan**, right-click pans too, mouse wheel
    // zooms (wheel zoom is governed by `enableZoom`, not by the button
    // table — remapping MIDDLE doesn't break it). Touch keeps the
    // standard one-finger rotate / two-finger dolly+pan combo.
    const enableEverything = () => {
      ctrl.enabled = true;
      ctrl.enableRotate = true;
      ctrl.enableZoom = true;
      ctrl.enablePan = true;
      ctrl.mouseButtons.LEFT = MOUSE.ROTATE;
      ctrl.mouseButtons.MIDDLE = MOUSE.PAN;
      ctrl.mouseButtons.RIGHT = MOUSE.PAN;
      ctrl.touches.ONE = TOUCH.ROTATE;
      ctrl.touches.TWO = TOUCH.DOLLY_PAN;
    };

    // Focused-on-a-part state: lock rotate + zoom (the camera is parked
    // on the assembly), but ENABLE pan so the operator can drag the
    // printer aside when the side-by-side popup is covering most of the
    // canvas. Left-click drag pans, two-finger drag pans on touch — no
    // hidden right-click discovery required.
    const enablePanOnly = () => {
      ctrl.enabled = true;
      ctrl.enableRotate = false;
      ctrl.enableZoom = false;
      ctrl.enablePan = true;
      ctrl.mouseButtons.LEFT = MOUSE.PAN;
      ctrl.mouseButtons.MIDDLE = MOUSE.PAN;
      ctrl.mouseButtons.RIGHT = MOUSE.PAN;
      ctrl.touches.ONE = TOUCH.PAN;
      ctrl.touches.TWO = TOUCH.PAN;
    };

    // Open mode — full freedom at the current pose.
    if (cameraOpen) {
      enableEverything();
      ctrl.update();
      return;
    }

    if (!selectedId) {
      enableEverything();
      applyPose(camera, ctrl, OVERVIEW_POS, OVERVIEW_LOOK_AT);
      return;
    }

    const focus = FOCUS[selectedId];
    if (!focus) {
      enableEverything();
      applyPose(camera, ctrl, OVERVIEW_POS, OVERVIEW_LOOK_AT);
      return;
    }

    const pos = focus.position.clone();
    const look = focus.lookAt.clone();
    if (isHoodSmartLiftTarget(selectedId)) {
      const t = Math.min(1, hoodSmartLiftMeters.current / HOOD_SMART_LIFT_DELTA);
      pos.y += 0.38 * t;
      pos.z += 0.22 * t;
      look.y += 0.18 * t;
    }

    applyPose(camera, ctrl, pos, look);
    enablePanOnly();
  }, [camera, selectedId, cameraOpen]);

  return (
    <OrbitControls
      ref={controlsRef}
      enableDamping
      dampingFactor={0.07}
      enablePan
      minDistance={5.5}
      maxDistance={20}
      maxPolarAngle={Math.PI / 2 - 0.05}
      minPolarAngle={Math.PI / 6}
      rotateSpeed={0.55}
      zoomSpeed={0.7}
      target={[-0.8, 1.7, 0]}
    />
  );
}
