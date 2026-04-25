import { motion, AnimatePresence } from "framer-motion";
import { PanelRight, PanelRightClose } from "lucide-react";
import { useTwin } from "@/store/twin";

const APPLE_EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

/**
 * SidebarToggle — explicit, native-feeling control for the right-hand
 * dashboard panel.
 *
 *   • Top-right corner, glassmorphic icon.
 *   • Low opacity (40%) until hovered → effectively invisible chrome.
 *   • Hidden during a component zoom: the dashboard is auto-suppressed
 *     anyway, so showing the toggle would be misleading. It re-appears the
 *     moment the user zooms back out.
 *   • Icon swaps between `PanelRightClose` (dashboard open) and
 *     `PanelRight` (dashboard hidden) so the affordance is unambiguous.
 */
export function SidebarToggle() {
  const dashboardOpen = useTwin((s) => s.dashboardOpen);
  const toggle = useTwin((s) => s.toggleDashboard);
  const selectedId = useTwin((s) => s.selectedComponentId);

  if (selectedId) return null;

  return (
    <motion.button
      type="button"
      onClick={toggle}
      title={dashboardOpen ? "Hide dashboard" : "Show dashboard"}
      aria-label={dashboardOpen ? "Hide dashboard" : "Show dashboard"}
      aria-pressed={dashboardOpen}
      initial={{ opacity: 0, scale: 0.92 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.92 }}
      transition={{ duration: 0.28, ease: APPLE_EASE }}
      className="
        fixed top-6 right-6 z-40
        h-9 w-9 rounded-full
        flex items-center justify-center
        text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]
        opacity-40 hover:opacity-100
        transition-opacity duration-200 ease-out
        glass-floating
      "
    >
      <AnimatePresence mode="wait" initial={false}>
        {dashboardOpen ? (
          <motion.span
            key="close"
            initial={{ opacity: 0, rotate: -8 }}
            animate={{ opacity: 1, rotate: 0 }}
            exit={{ opacity: 0, rotate: 8 }}
            transition={{ duration: 0.16 }}
          >
            <PanelRightClose size={15} />
          </motion.span>
        ) : (
          <motion.span
            key="open"
            initial={{ opacity: 0, rotate: 8 }}
            animate={{ opacity: 1, rotate: 0 }}
            exit={{ opacity: 0, rotate: -8 }}
            transition={{ duration: 0.16 }}
          >
            <PanelRight size={15} />
          </motion.span>
        )}
      </AnimatePresence>
    </motion.button>
  );
}
