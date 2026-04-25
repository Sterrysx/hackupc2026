import { motion } from "framer-motion";
import { ComponentFocus } from "@/components/sidebar/ComponentFocus";
import { groupPairFor } from "@/lib/componentMap";
import type { ComponentId } from "@/types/telemetry";

const APPLE_EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

/**
 * ARDataCard — the spatially-anchored "AR tag" that pops up next to the
 * focused assembly once the schematic / 3D zoom settles.
 *
 * Each click — in 2D or 3D, on either half of an assembly — opens the SAME
 * card showing **both parts of that 3D assembly side-by-side**. The 3D model
 * groups the six components into three physical assemblies (recoater =
 * blade+motor, printhead = plate+resistor, build unit = heater+insulation),
 * so a single inspection surface for the whole pair keeps the operator's
 * mental model consistent across views.
 *
 *   - Lands at the right edge but enters with an offset *toward the centre*
 *     of the canvas, so it visually feels like it's emerging from the part.
 *   - Width scales with the viewport: ~720px on desktop, capped to fit
 *     comfortably on smaller screens.
 */
export function ARDataCard({ id }: { id: ComponentId }) {
  const [primaryId, secondaryId] = groupPairFor(id);
  const isPair = primaryId !== secondaryId;

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
        width: isPair ? "min(720px, calc(100vw - 48px))" : "min(360px, calc(100vw - 48px))",
      }}
    >
      <div className="flex-1 min-h-0 overflow-y-auto">
        {isPair ? (
          <div className="grid grid-cols-2 divide-x divide-[var(--color-border)]">
            <ComponentFocus id={primaryId} />
            <ComponentFocus id={secondaryId} />
          </div>
        ) : (
          <ComponentFocus id={primaryId} />
        )}
      </div>
    </motion.aside>
  );
}
