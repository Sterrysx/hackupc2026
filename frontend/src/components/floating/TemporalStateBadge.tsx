import { AnimatePresence, motion } from "framer-motion";
import { Sparkles } from "lucide-react";
import { useTwin } from "@/store/twin";

/**
 * TemporalStateBadge — top-left ethereal indicator that swaps between two
 * states based on the predictive scrubber position.
 *
 * 0 days       → soft glowing green dot + "Live Telemetry" label
 * > 0 days     → frosted glass cyan pill + "Predictive Forecast +Nd"
 *
 * The two never coexist (AnimatePresence mode="wait"), so the operator
 * sees a single clean source of truth for "what time is the UI showing".
 *
 * Spring values are intentionally over-damped (mass 0.9, damping 30) so
 * the swap reads as a slow weighty fade rather than a snap — which keeps
 * the chrome out of the way during everyday scrubbing.
 */

const SPRING = { type: "spring" as const, stiffness: 230, damping: 30, mass: 0.9 };
const FADE = { duration: 0.32, ease: [0.16, 1, 0.3, 1] as const };

export function TemporalStateBadge() {
  const horizon = useTwin((s) => s.forecastHorizonDays);
  const isLive = horizon < 0.05;

  return (
    <div className="fixed top-6 left-1/2 -translate-x-1/2 z-30 pointer-events-none">
      <AnimatePresence mode="wait" initial={false}>
        {isLive ? (
          <motion.div
            key="live"
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={FADE}
            className="
              inline-flex items-center gap-2 px-3 h-7 rounded-full
              bg-white/[0.04] backdrop-blur-md
              border border-white/[0.06]
              text-[11px] tracking-tight text-[var(--color-fg-muted)]
            "
          >
            <span className="relative inline-flex h-2 w-2">
              <span
                className="absolute inset-0 rounded-full bg-emerald-400/55 animate-pulse"
                style={{ filter: "blur(3px)" }}
                aria-hidden
              />
              <span className="relative inline-block h-2 w-2 rounded-full bg-emerald-300" />
            </span>
            <span>Live Telemetry</span>
          </motion.div>
        ) : (
          <motion.div
            key="predictive"
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={SPRING}
            className="
              inline-flex items-center gap-2 px-3.5 h-8 rounded-full
              text-[11.5px] tracking-tight text-cyan-50
            "
            style={{
              background:
                "linear-gradient(135deg, rgba(126,195,255,0.18) 0%, rgba(95,170,228,0.08) 100%)",
              backdropFilter: "blur(20px) saturate(160%)",
              WebkitBackdropFilter: "blur(20px) saturate(160%)",
              border: "1px solid rgba(126,195,255,0.28)",
              boxShadow:
                "0 1px 0 rgba(255,255,255,0.10) inset, 0 14px 40px -16px rgba(126,195,255,0.45)",
            }}
          >
            <Sparkles size={12} className="text-cyan-200" />
            <span className="font-medium">Predictive Forecast</span>
            <span className="tabular-nums text-cyan-200/70">+{horizon.toFixed(1)}d</span>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/**
 * PredictiveTint — full-screen overlay that picks up a faint cyan wash
 * the further into the future we scrub. Not part of the badge itself,
 * but lives in this file so the colour story stays in one place.
 *
 * Pointer-events-none so it never intercepts clicks. Driven by a CSS
 * variable that the consumer sets from the store, so the React tree
 * doesn't re-render on every horizon tick — only the gradient updates.
 */
export function PredictiveTint() {
  const horizon = useTwin((s) => s.forecastHorizonDays);
  const horizonMax = useTwin((s) => s.forecastHorizonMax);
  const t = Math.min(1, horizon / horizonMax);
  // Quadratic easing — subtle at first, more visible at the right edge.
  const intensity = 0.16 * t * t;
  return (
    <div
      aria-hidden
      className="fixed inset-0 z-[5] pointer-events-none transition-[opacity] duration-500"
      style={{
        opacity: t > 0 ? 1 : 0,
        background: `radial-gradient(ellipse 80% 60% at 50% 100%,
          rgba(126,195,255,${intensity}) 0%,
          rgba(126,195,255,${intensity * 0.5}) 35%,
          transparent 75%)`,
      }}
    />
  );
}
