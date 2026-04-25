import { motion } from "framer-motion";
import { useTwin } from "@/store/twin";
import { cn } from "@/lib/cn";

const OPTIONS: Array<{ value: "immersive" | "dashboard"; label: string }> = [
  { value: "immersive", label: "Immersive" },
  { value: "dashboard", label: "Dashboard" },
];

/**
 * iOS-style segmented control floating at the top centre.
 * The "thumb" (active background pill) is layoutId-tweened by framer-motion,
 * so it slides smoothly between the two options.
 */
export function ModeToggle() {
  const mode = useTwin((s) => s.mode);
  const setMode = useTwin((s) => s.setMode);

  return (
    <div className="fixed top-6 left-1/2 -translate-x-1/2 z-30">
      <div className="relative inline-flex items-center p-1 rounded-full glass-floating">
        {OPTIONS.map((opt) => {
          const active = mode === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => setMode(opt.value)}
              className={cn(
                "relative h-8 px-5 rounded-full text-[12px] font-medium tracking-tight transition-colors",
                active ? "text-[var(--color-fg)]" : "text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]",
              )}
            >
              {active && (
                <motion.span
                  layoutId="modeToggleThumb"
                  className="absolute inset-0 rounded-full bg-white/[0.10]"
                  transition={{ type: "spring", stiffness: 380, damping: 32 }}
                />
              )}
              <span className="relative z-10">{opt.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
