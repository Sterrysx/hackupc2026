import { motion } from "framer-motion";
import { ComponentFocus } from "@/components/sidebar/ComponentFocus";
import type { ComponentId } from "@/types/telemetry";

const APPLE_EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

/**
 * ARDataCard — the spatially-anchored "AR tag" that pops up next to the
 * focused component once the schematic zoom settles.
 *
 *   - Lands at the right edge but enters with an offset *toward the centre*
 *     of the canvas, so it visually feels like it's emerging from the part.
 *   - Smaller and centred vertically (vs the dashboard widget's full-height
 *     layout), so it doesn't compete with the bubble at the bottom.
 */
export function ARDataCard({ id }: { id: ComponentId }) {
  return (
    <motion.aside
      initial={{ opacity: 0, scale: 0.92, x: -24 }}
      animate={{ opacity: 1, scale: 1, x: 0 }}
      exit={{ opacity: 0, scale: 0.94, x: -10 }}
      transition={{ duration: 0.42, ease: APPLE_EASE }}
      className="
        fixed top-1/2 right-6 -translate-y-1/2 z-20
        w-[360px] max-h-[78vh]
        flex flex-col overflow-hidden
        rounded-[28px] glass-floating
      "
    >
      <div className="flex-1 min-h-0 overflow-y-auto">
        <ComponentFocus id={id} />
      </div>
    </motion.aside>
  );
}
