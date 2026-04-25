import { motion, AnimatePresence } from "framer-motion";
import { Sparkles, X } from "lucide-react";
import { useTwin } from "@/store/twin";

/**
 * Floating chat button — Apple-FAB feel.
 *  - Lives at bottom-right, always visible.
 *  - Becomes a soft "x" while chat is open so the affordance is clear.
 */
export function FloatingChatButton() {
  const { chatOpen, setChatOpen, alerts } = useTwin();
  const critCount = alerts.filter((a) => a.severity === "CRITICAL").length;

  return (
    <button
      type="button"
      onClick={() => setChatOpen(!chatOpen)}
      title={chatOpen ? "Close Aether" : "Open Aether"}
      className="
        fixed bottom-6 right-6 z-50
        h-14 w-14 rounded-full
        flex items-center justify-center
        glass-floating
        hover:scale-105 active:scale-95
        transition-transform duration-200 ease-out
      "
    >
      <AnimatePresence mode="wait" initial={false}>
        {chatOpen ? (
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

      {!chatOpen && critCount > 0 && (
        <span
          className="absolute -top-0.5 -right-0.5 h-3 w-3 rounded-full"
          style={{
            background: "var(--color-crit)",
            border: "2px solid oklch(0.20 0.003 260)",
          }}
        />
      )}
    </button>
  );
}
