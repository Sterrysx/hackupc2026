import { motion } from "framer-motion";
import { Loader2, Play } from "lucide-react";
import { useTwin } from "@/store/twin";

/**
 * ExecutePrintButton — primary "action" affordance, in the same chrome
 * vocabulary as BrandMark / ViewToggle / SidebarToggle: dark glass pill,
 * muted text, single accent dot for state.
 *
 *   ┌─────────────────────────────┐
 *   │ ▸  Execute print            │   ← idle: dark glass, muted label
 *   └─────────────────────────────┘
 *   ┌─────────────────────────────┐
 *   │ ⟳  Spreading powder…        │   ← active: same shell, spinner + accent
 *   └─────────────────────────────┘
 *
 * Floats top-center, just to the right of the temporal badge. Tap → flips
 * `executingPrint` true; the store auto-clears after 5 s. The 3D animation
 * is wired in `MachineModel`, not here.
 */

const APPLE_EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

export function ExecutePrintButton() {
  const executing = useTwin((s) => s.executingPrint);
  const trigger = useTwin((s) => s.executePrint);
  const selectedId = useTwin((s) => s.selectedComponentId);

  // Hidden during a component zoom — printing is a global action, not part
  // of the focused inspection surface. Mirrors ViewToggle / SidebarToggle.
  if (selectedId) return null;

  return (
    <motion.button
      type="button"
      onClick={trigger}
      disabled={executing}
      title={executing ? "Print job in progress" : "Execute print"}
      aria-label={executing ? "Print job in progress" : "Execute print"}
      aria-pressed={executing}
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, ease: APPLE_EASE }}
      whileTap={executing ? undefined : { scale: 0.98 }}
      className="
        fixed top-6 right-1/2 translate-x-[calc(50%+170px)] z-30
        inline-flex items-center gap-2 h-9 pl-3 pr-4 rounded-full
        glass-floating select-none
        text-[12px] font-medium tracking-tight
        text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]
        transition-colors duration-200 ease-out
        disabled:cursor-default disabled:hover:text-[var(--color-fg-muted)]
      "
    >
      {/* Status dot mirrors BrandMark's heartbeat — soft accent while idle, soft pulse while running. */}
      <span
        aria-hidden
        className="h-1.5 w-1.5 rounded-full flex-shrink-0"
        style={{
          background: executing ? "var(--color-warn)" : "var(--color-accent)",
          animation: executing ? "softPulse 1.4s ease-in-out infinite" : undefined,
        }}
      />
      <span className="relative inline-flex items-center justify-center w-3.5 h-3.5">
        {executing ? (
          <Loader2 size={12} className="animate-spin" aria-hidden />
        ) : (
          <Play size={11} className="translate-x-[1px]" aria-hidden />
        )}
      </span>
      <span>{executing ? "Spreading powder…" : "Execute print"}</span>
    </motion.button>
  );
}
