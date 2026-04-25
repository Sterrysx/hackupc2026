import { motion } from "framer-motion";
import { OverviewPanel } from "@/components/sidebar/OverviewPanel";

/**
 * Floating dashboard widget — visible iff:
 *   `dashboardOpen && !selectedComponentId`
 *
 * The panel is strictly at-a-glance telemetry + alerts; chat lives in the
 * Spotlight overlay. Slides in/out with a heavy spring so it lands like a
 * native macOS sidebar instead of a CSS modal.
 */
const PANEL_SPRING = { type: "spring" as const, stiffness: 220, damping: 30, mass: 0.9 };

export function DashboardPanel() {
  return (
    <motion.aside
      initial={{ opacity: 0, x: 36 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 36 }}
      transition={PANEL_SPRING}
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
    </motion.aside>
  );
}
