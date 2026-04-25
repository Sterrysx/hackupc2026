import { motion } from "framer-motion";
import { OverviewPanel } from "@/components/sidebar/OverviewPanel";
import { EmbeddedChat } from "@/components/sidebar/EmbeddedChat";

const APPLE_EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

/**
 * The main floating dashboard widget — visible when:
 *   mode === "dashboard"  AND  no component is selected.
 *
 * Glass pane hovering over the schematic. Top section is the live overview
 * (status hero, components list, alerts, environment); bottom section is the
 * Aether chat. Top/bottom margins of 24px so it never touches the edges.
 */
export function DashboardPanel() {
  return (
    <motion.aside
      initial={{ opacity: 0, scale: 0.96, x: 12 }}
      animate={{ opacity: 1, scale: 1, x: 0 }}
      exit={{ opacity: 0, scale: 0.95, x: 8 }}
      transition={{ duration: 0.32, ease: APPLE_EASE }}
      className="
        fixed top-6 right-6 bottom-6 z-20
        w-[400px] xl:w-[440px]
        flex flex-col overflow-hidden
        rounded-[28px] glass-floating
      "
    >
      <div className="flex-1 min-h-0 overflow-y-auto">
        <OverviewPanel />
      </div>
      <div className="h-[42%] min-h-[260px] max-h-[440px] flex flex-col flex-shrink-0">
        <EmbeddedChat />
      </div>
    </motion.aside>
  );
}
