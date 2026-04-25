import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Pause, Play } from "lucide-react";
import { useTwin } from "@/store/twin";

/**
 * PredictiveScrubber — bottom-center transport that owns the temporal axis.
 * Visual vocabulary aligned with the rest of the floating chrome:
 *   - `glass-floating` dark pill, `rounded-full`
 *   - muted resting text + `text-[var(--color-fg)]` on the active state
 *   - single accent for the fill (no rainbow gradient)
 *   - segmented speed picker matching ViewToggle's tab pattern
 *
 * Left edge (0%) = NOW (live mode); right edge (100%) =
 * `forecastHorizonMax` days into the future.
 *
 * The scrubber DOES NOT advance the simulator's `tick`. It only writes to
 * `forecastHorizonDays`. Whoever consumes it (badge, panels, future data
 * widgets) is responsible for picking the right snapshot/forecast frame.
 */

// 10-year horizon ≈ 3 652 days. At 1× we want the full horizon to play in
// ~30 s wall-clock, which sets the base rate at ~120 sim-days/sec. Faster
// speed picks let the operator skim across years in seconds.
const BASE_DAYS_PER_SEC = 120;
const SPEEDS = [1, 2, 4, 8] as const;
const APPLE_EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

/** Format a day-offset compactly: <60d → "+Nd", <2y → "+Nmo", else "+Ny". */
function formatHorizonOffset(days: number): string {
  if (days < 1) return `+${days.toFixed(1)}d`;
  if (days < 60) return `+${days.toFixed(0)}d`;
  if (days < 730) return `+${Math.round(days / 30)}mo`;
  return `+${(days / 365).toFixed(1)}y`;
}

export function PredictiveScrubber() {
  const horizon = useTwin((s) => s.forecastHorizonDays);
  const horizonMax = useTwin((s) => s.forecastHorizonMax);
  const playing = useTwin((s) => s.forecastPlaying);
  const speed = useTwin((s) => s.forecastSpeed);
  const setHorizon = useTwin((s) => s.setForecastHorizon);
  const setPlaying = useTwin((s) => s.setForecastPlaying);
  const setSpeed = useTwin((s) => s.setForecastSpeed);
  const resetToLive = useTwin((s) => s.resetToLive);
  const selectedId = useTwin((s) => s.selectedComponentId);

  // Decouple the visible thumb from the store while the user is mid-drag —
  // otherwise an in-flight rAF tick can yank the slider back under their
  // finger. Released on pointer-up.
  const [scrubDays, setScrubDays] = useState<number | null>(null);
  const displayDays = scrubDays !== null ? scrubDays : horizon;
  const fillPct = (displayDays / Math.max(1, horizonMax)) * 100;
  const isLive = displayDays < 0.05;

  // ── rAF auto-advance ───────────────────────────────────────────────────
  const lastTsRef = useRef<number | null>(null);
  useEffect(() => {
    if (!playing) {
      lastTsRef.current = null;
      return;
    }
    let rafId = 0;
    const tick = (ts: number) => {
      if (lastTsRef.current === null) lastTsRef.current = ts;
      const dt = (ts - lastTsRef.current) / 1000;
      lastTsRef.current = ts;
      const current = useTwin.getState().forecastHorizonDays;
      const cap = useTwin.getState().forecastHorizonMax;
      const sp = useTwin.getState().forecastSpeed;
      const next = current + dt * BASE_DAYS_PER_SEC * sp;
      if (next >= cap) {
        setHorizon(cap);
        setPlaying(false);
        return;
      }
      setHorizon(next);
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(rafId);
      lastTsRef.current = null;
    };
  }, [playing, setHorizon, setPlaying]);

  // Hide while a component is zoomed — same rule as the rest of the chrome.
  if (selectedId) return null;

  // ── handlers ───────────────────────────────────────────────────────────
  function onScrub(e: React.ChangeEvent<HTMLInputElement>) {
    const days = Number(e.target.value);
    setScrubDays(days);
    setHorizon(days);
  }
  function release() {
    setScrubDays(null);
  }
  function onPlayPause() {
    setPlaying(!playing);
  }
  function onPickSpeed(s: number) {
    setSpeed(s);
    if (!playing) setPlaying(true);
  }
  function onTapLive() {
    resetToLive();
  }

  return (
    <motion.div
      initial={{ y: 16, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      exit={{ y: 16, opacity: 0 }}
      transition={{ duration: 0.32, ease: APPLE_EASE }}
      className="
        fixed bottom-6 left-1/2 z-30 -translate-x-1/2
        rounded-full glass-floating select-none
        px-3 py-2
      "
      style={{ width: "min(640px, calc(100vw - 48px))" }}
    >
      <div className="flex items-center gap-2.5">
        {/* Live ↔ Predictive lozenge — taps reset to NOW. Mirrors BrandMark
            (heartbeat dot + tracking-tight label) so it reads as part of
            the same family rather than a separate accent. */}
        <button
          type="button"
          onClick={onTapLive}
          title={isLive ? "Currently in Live Mode" : "Snap back to NOW"}
          className={
            "inline-flex items-center gap-2 h-7 pl-2.5 pr-3 rounded-full " +
            "transition-colors duration-200 ease-out " +
            (isLive
              ? "text-[var(--color-fg)]"
              : "text-[var(--color-fg-muted)] hover:text-[var(--color-fg)] hover:bg-white/[0.06]")
          }
        >
          <span
            aria-hidden
            className="h-1.5 w-1.5 rounded-full flex-shrink-0"
            style={{
              background: isLive ? "var(--color-ok)" : "var(--color-accent)",
              animation: isLive ? "softPulse 2.4s ease-in-out infinite" : undefined,
            }}
          />
          <span className="text-[11px] font-medium tracking-tight tabular-nums">
            {isLive ? "Now" : formatHorizonOffset(displayDays)}
          </span>
        </button>

        {/* Play/pause — same circular icon button as SidebarToggle. */}
        <button
          type="button"
          onClick={onPlayPause}
          title={playing ? "Pause forecast" : "Play forecast forward"}
          aria-pressed={playing}
          className="
            inline-flex items-center justify-center h-7 w-7 rounded-full
            text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]
            hover:bg-white/[0.06]
            transition-colors duration-200 ease-out
          "
        >
          {playing ? <Pause size={12} /> : <Play size={12} className="translate-x-[1px]" />}
        </button>

        {/* The scrubber track. Single-color accent fill — no rainbow. */}
        <div className="flex-1 min-w-0 relative">
          <input
            type="range"
            min={0}
            max={horizonMax}
            step={0.1}
            value={displayDays}
            onChange={onScrub}
            onPointerUp={release}
            onPointerCancel={release}
            onBlur={release}
            aria-label="Predictive forecast horizon"
            className="timeline-scrub w-full h-[5px] rounded-full appearance-none cursor-pointer"
            style={{
              background: `linear-gradient(to right,
                var(--color-fg) 0%,
                var(--color-fg) ${fillPct}%,
                rgba(255,255,255,0.08) ${fillPct}%,
                rgba(255,255,255,0.08) 100%)`,
              boxShadow: `inset 0 0 0 1px rgba(255,255,255,0.04)`,
            }}
          />
          {/* Tick markers — quartile labels formatted on the same horizon
              scale as the lozenge so the eye reads "Now → +Ny" without
              mental conversion. */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 -bottom-3 flex justify-between
                       text-[9px] uppercase tracking-[0.18em] text-[var(--color-fg-faint)]"
          >
            <span>Now</span>
            <span>{formatHorizonOffset(horizonMax * 0.25)}</span>
            <span>{formatHorizonOffset(horizonMax * 0.5)}</span>
            <span>{formatHorizonOffset(horizonMax * 0.75)}</span>
            <span>{formatHorizonOffset(horizonMax)}</span>
          </div>
        </div>

        {/* Speed picker — same segmented-pill pattern as ViewToggle, with a
            shared `layoutId` thumb gliding between options. */}
        <div className="flex items-center p-0.5 rounded-full bg-white/[0.04]">
          {SPEEDS.map((s) => {
            const active = s === speed;
            return (
              <button
                key={s}
                type="button"
                onClick={() => onPickSpeed(s)}
                aria-pressed={active}
                className={
                  "relative h-6 px-2 rounded-full text-[10.5px] font-medium tracking-tight tabular-nums " +
                  "transition-colors " +
                  (active
                    ? "text-[var(--color-fg)]"
                    : "text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]")
                }
              >
                {active && (
                  <motion.span
                    layoutId="scrubSpeedThumb"
                    className="absolute inset-0 rounded-full bg-white/[0.12]"
                    transition={{ type: "spring", stiffness: 360, damping: 32, mass: 0.7 }}
                  />
                )}
                <span className="relative z-10">{s}×</span>
              </button>
            );
          })}
        </div>
      </div>
    </motion.div>
  );
}
