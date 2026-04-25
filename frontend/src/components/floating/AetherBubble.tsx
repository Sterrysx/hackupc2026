import { AnimatePresence, motion } from "framer-motion";
import { Sparkles, X } from "lucide-react";
import { useTwin } from "@/store/twin";
import { EmbeddedChat } from "@/components/sidebar/EmbeddedChat";

const APPLE_EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

/**
 * AetherBubble — floating chat surface that appears whenever the dashboard
 * widget is hidden (immersive mode, or any component is selected).
 *
 *   - Collapsed: a 56×56 glass FAB at bottom-right with a sparkles glyph.
 *   - Expanded: a glass chat panel anchored just above the FAB.
 *
 * A small coral dot appears on the FAB when a critical alert is active.
 */
export function AetherBubble() {
  const open = useTwin((s) => s.bubbleOpen);
  const setOpen = useTwin((s) => s.setBubbleOpen);
  const alerts = useTwin((s) => s.alerts);

  const critCount = alerts.filter((a) => a.severity === "CRITICAL").length;

  return (
    <>
      {/* FAB */}
      <motion.button
        type="button"
        initial={{ opacity: 0, scale: 0.85 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 0.9 }}
        transition={{ duration: 0.3, ease: APPLE_EASE }}
        onClick={() => setOpen(!open)}
        title={open ? "Close Aether" : "Open Aether"}
        className="fixed bottom-6 right-6 z-40 h-14 w-14 rounded-full glass-floating flex items-center justify-center hover:scale-105 active:scale-95 transition-transform"
      >
        <AnimatePresence mode="wait" initial={false}>
          {open ? (
            <motion.span
              key="x"
              initial={{ rotate: -45, opacity: 0 }}
              animate={{ rotate: 0, opacity: 1 }}
              exit={{ rotate: 45, opacity: 0 }}
              transition={{ duration: 0.18 }}
              className="text-[var(--color-fg)]"
            >
              <X size={18} />
            </motion.span>
          ) : (
            <motion.span
              key="sparkles"
              initial={{ scale: 0.85, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.85, opacity: 0 }}
              transition={{ duration: 0.18 }}
              className="text-[var(--color-accent)]"
            >
              <Sparkles size={18} />
            </motion.span>
          )}
        </AnimatePresence>

        {!open && critCount > 0 && (
          <span
            className="absolute -top-0.5 -right-0.5 h-3 w-3 rounded-full"
            style={{
              background: "var(--color-crit)",
              border: "2px solid oklch(0.18 0.003 260)",
            }}
          />
        )}
      </motion.button>

      {/* Expanded panel */}
      <AnimatePresence>
        {open && (
          <motion.div
            key="bubble-panel"
            initial={{ opacity: 0, scale: 0.94, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 4 }}
            transition={{ duration: 0.32, ease: APPLE_EASE }}
            className="
              fixed bottom-24 right-6 z-30
              w-[380px] h-[min(540px,68vh)]
              flex flex-col overflow-hidden
              rounded-[28px] glass-floating
            "
            style={{ transformOrigin: "bottom right" }}
          >
            <EmbeddedChat />
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
