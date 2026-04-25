import { motion } from "framer-motion";
import { cn } from "@/lib/cn";
import { AnimatedNumber } from "@/components/AnimatedNumber";

interface HealthRingProps {
  /** Current health 0..1 */
  value: number;
  /** Predicted health 0..1 — drawn as a faint inner trace. */
  predicted?: number;
  size?: number;
  thickness?: number;
  className?: string;
  /** When false (default) the number is hidden — the ring is purely visual. */
  showValue?: boolean;
}

/**
 * HealthRing — visual-only by default.
 *  - No drop-shadow / glow.
 *  - Soft, low-saturation colours.
 *  - Predicted ring is a thin, semi-transparent inner trace; never competes with current.
 */
export function HealthRing({
  value,
  predicted,
  size = 28,
  thickness = 3,
  className,
  showValue = false,
}: HealthRingProps) {
  const radius = (size - thickness) / 2;
  const circ = 2 * Math.PI * radius;
  const colour = colourForHealth(value);
  const predColour = predicted !== undefined ? colourForHealth(predicted) : undefined;

  return (
    <div
      className={cn("relative inline-flex items-center justify-center", className)}
      style={{ width: size, height: size }}
    >
      <svg width={size} height={size} className="-rotate-90 overflow-visible">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="oklch(1 0 0 / 0.10)"
          strokeWidth={thickness}
        />
        {predicted !== undefined && predicted < value - 0.02 && (
          <motion.circle
            cx={size / 2}
            cy={size / 2}
            r={radius - thickness * 0.9}
            fill="none"
            stroke={predColour}
            strokeWidth={Math.max(1, thickness - 1.5)}
            strokeLinecap="round"
            strokeDasharray={2 * Math.PI * (radius - thickness * 0.9)}
            initial={{ strokeDashoffset: 2 * Math.PI * (radius - thickness * 0.9) }}
            animate={{
              strokeDashoffset:
                2 * Math.PI * (radius - thickness * 0.9) * (1 - clamp01(predicted)),
            }}
            transition={{ duration: 0.7, ease: "easeOut" }}
            opacity={0.32}
          />
        )}
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={colour}
          strokeWidth={thickness}
          strokeLinecap="round"
          strokeDasharray={circ}
          initial={{ strokeDashoffset: circ }}
          animate={{ strokeDashoffset: circ * (1 - clamp01(value)) }}
          transition={{ duration: 0.6, ease: "easeOut" }}
        />
      </svg>
      {showValue && (
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <AnimatedNumber
            value={value * 100}
            className="font-medium tabular-nums tracking-tight text-[var(--color-fg)] leading-none"
            duration={0.6}
            style={{ fontSize: Math.max(10, size * 0.28) }}
          />
        </div>
      )}
    </div>
  );
}

function colourForHealth(h: number): string {
  if (h <= 0.20) return "oklch(0.72 0.13 25)";   // crit (coral)
  if (h <= 0.50) return "oklch(0.83 0.12 75)";   // warn (sand)
  if (h <= 0.75) return "oklch(0.78 0.10 240)";  // info (blue)
  return "oklch(0.78 0.10 155)";                  // ok (mint)
}

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v));
}
