import { motion, AnimatePresence } from "framer-motion";
import { Lock, LockOpen } from "lucide-react";
import { useTwin } from "@/store/twin";

const APPLE_EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

/**
 * OpenViewButton — appears only when a 3D component is focused.
 * "Open" unlocks camera controls so the operator can pan/orbit while focused.
 */
export function OpenViewButton() {
  const selectedId = useTwin((s) => s.selectedComponentId);
  const viewMode = useTwin((s) => s.viewMode);
  const cameraOpen = useTwin((s) => s.cameraOpen);
  const setCameraOpen = useTwin((s) => s.setCameraOpen);

  if (!selectedId || viewMode !== "3d") return null;

  return (
    <motion.button
      type="button"
      onClick={() => setCameraOpen(!cameraOpen)}
      title={cameraOpen ? "Lock camera focus" : "Open camera controls"}
      aria-label={cameraOpen ? "Lock camera focus" : "Open camera controls"}
      aria-pressed={cameraOpen}
      initial={{ opacity: 0, scale: 0.92 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.92 }}
      transition={{ duration: 0.28, ease: APPLE_EASE }}
      className="
        fixed top-6 right-20 z-40
        h-9 w-9 rounded-full
        flex items-center justify-center
        text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]
        opacity-40 hover:opacity-100
        transition-opacity duration-200 ease-out
        glass-floating
      "
    >
      <AnimatePresence mode="wait" initial={false}>
        {cameraOpen ? (
          <motion.span
            key="open"
            initial={{ opacity: 0, rotate: -8 }}
            animate={{ opacity: 1, rotate: 0 }}
            exit={{ opacity: 0, rotate: 8 }}
            transition={{ duration: 0.16 }}
          >
            <LockOpen size={15} />
          </motion.span>
        ) : (
          <motion.span
            key="locked"
            initial={{ opacity: 0, rotate: 8 }}
            animate={{ opacity: 1, rotate: 0 }}
            exit={{ opacity: 0, rotate: -8 }}
            transition={{ duration: 0.16 }}
          >
            <Lock size={15} />
          </motion.span>
        )}
      </AnimatePresence>
    </motion.button>
  );
}
