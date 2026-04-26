import { motion } from "framer-motion";
import { ComponentFocus } from "@/components/sidebar/ComponentFocus";
import { groupPairFor } from "@/lib/componentMap";
import { useTwin } from "@/store/twin";
import type { ComponentId } from "@/types/telemetry";

const APPLE_EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

/**
 * ARDataCard — the spatially-anchored "AR tag" that pops up next to the
 * focused assembly once the schematic / 3D zoom settles.
 *
 * View-aware behaviour:
 *  - **3D**: every clickable mesh in the scene represents an *assembly* of
 *    two components (recoater = blade+motor, printhead = plate+resistor,
 *    build unit = heater+insulation). Clicking opens BOTH halves
 *    side-by-side because that's what the operator selected on the model.
 *  - **2D / analytics / anywhere else**: the schematic exposes all six
 *    components individually. Clicking should inspect *just* the picked
 *    one — pairing them up here would be misleading.
 *
 *  - Lands at the right edge but enters with an offset *toward the centre*
 *    of the canvas, so it visually feels like it's emerging from the part.
 *  - Width scales with the viewport: ~720 px in pair mode, ~360 px solo.
 */
export function ARDataCard({ id }: { id: ComponentId }) {
  const viewMode = useTwin((s) => s.viewMode);
  const [primaryId, secondaryId] = groupPairFor(id);
  // Only the 3D scene clicks on assemblies, so only there should the pair
  // expand. 2D and analytics keep the focused single-component card.
  const showPair = viewMode === "3d" && primaryId !== secondaryId;

  return (
    <motion.aside
      initial={{ opacity: 0, scale: 0.94, x: -24 }}
      animate={{ opacity: 1, scale: 1, x: 0 }}
      exit={{ opacity: 0, scale: 0.96, x: -10 }}
      transition={{ duration: 0.42, ease: APPLE_EASE }}
      className="
        fixed top-1/2 right-6 -translate-y-1/2 z-20
        max-h-[82vh]
        flex flex-col overflow-hidden
        rounded-[28px] glass-floating
      "
      style={{
        width: showPair ? "min(720px, calc(100vw - 48px))" : "min(360px, calc(100vw - 48px))",
      }}
    >
      <div className="flex-1 min-h-0 overflow-y-auto">
        {showPair ? (
          <div className="grid grid-cols-2 divide-x divide-[var(--color-border)]">
            <ComponentFocus id={primaryId} />
            <ComponentFocus id={secondaryId} />
          </div>
        ) : (
          <ComponentFocus id={id} />
        )}
      </div>
    </motion.aside>
  );
}
