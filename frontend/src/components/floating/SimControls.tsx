import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Pause, Play, RotateCcw, FastForward, Command,
  ChevronUp, ChevronDown, SkipBack, SkipForward,
} from "lucide-react";
import { useTwin } from "@/store/twin";
import { Button } from "@/components/ui/Button";
import { TICKS_PER_DAY, SIM_DAY_COUNT, tickToDay } from "@/lib/twinApi";

/**
 * Floating transport for the simulator.
 *
 * Apple-style progressive disclosure: the **collapsed** bar is a minimal
 * glass pill (play, speed cycle, +1d, reset, day counter). Hitting the
 * chevron **expands** it into a YouTube-style player with a scrub track
 * over the full 10-year sim, jump-by-day/week shortcuts, and a six-step
 * speed picker. All extra complexity stays hidden until the operator
 * asks for it.
 *
 * The simulator is *daily*: the parquet has one row per day and the RUL
 * head reasons in days, so the entire transport speaks days. No hours.
 */

const SIM_START_DATE_UTC = Date.UTC(2015, 0, 1);
const SPEED_STEPS = [1, 2, 4, 8, 16, 32] as const;

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="inline-flex items-center justify-center min-w-[16px] px-1 rounded bg-white/[0.08] border border-white/[0.10] text-[9.5px] font-medium text-[var(--color-fg-muted)]">
      {children}
    </kbd>
  );
}

function dayToISODate(day: number): string {
  const ms = SIM_START_DATE_UTC + day * 86_400_000;
  const d = new Date(ms);
  return d.toLocaleDateString(undefined, {
    weekday: "short", month: "short", day: "numeric", year: "numeric",
  });
}

export function SimControls() {
  const tick = useTwin((s) => s.tick);
  const paused = useTwin((s) => s.paused);
  const speed = useTwin((s) => s.speed);
  const setPaused = useTwin((s) => s.setPaused);
  const setSpeed = useTwin((s) => s.setSpeed);
  const jumpForward = useTwin((s) => s.jumpForward);
  const setTick = useTwin((s) => s.setTick);
  const reset = useTwin((s) => s.reset);
  const setCommandPaletteOpen = useTwin((s) => s.setCommandPaletteOpen);

  const [expanded, setExpanded] = useState(false);
  // Local thumb position while the user is actively dragging — decouples the
  // slider from the store so a slow live-mode fetch can't snap the thumb back
  // to its previous value mid-drag.
  const [scrubDay, setScrubDay] = useState<number | null>(null);

  const day = tickToDay(tick);
  const totalDays = SIM_DAY_COUNT;
  const sliderDay = scrubDay !== null ? scrubDay : day;
  const dateLabel = dayToISODate(sliderDay);
  const fillPct = (sliderDay / Math.max(1, totalDays - 1)) * 100;

  function onScrubInput(e: React.ChangeEvent<HTMLInputElement>) {
    const targetDay = Number(e.target.value);
    setScrubDay(targetDay);
    setTick(targetDay * TICKS_PER_DAY);
  }
  function onScrubRelease() {
    setScrubDay(null);
  }

  // Keyboard shortcuts — active only while the transport is expanded.
  // Suppressed when an input/textarea/contenteditable has focus, so chat &
  // search keep ←/→/space.
  useEffect(() => {
    if (!expanded) return;
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      if (t) {
        const tag = t.tagName;
        if (
          tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" ||
          t.isContentEditable
        ) return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const step = e.shiftKey ? 7 * TICKS_PER_DAY : TICKS_PER_DAY;
      if (e.key === "ArrowRight") { jumpForward(step); e.preventDefault(); }
      else if (e.key === "ArrowLeft") { jumpForward(-step); e.preventDefault(); }
      else if (e.key === " ") { setPaused(!paused); e.preventDefault(); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expanded, paused, setPaused, jumpForward]);

  // NOTE: no framer `layout` props on this container — they fight the native
  // range input by re-applying transforms during state updates. Width is
  // animated via plain CSS transition instead.
  return (
    <div
      className="fixed bottom-6 left-1/2 -translate-x-1/2 z-30 rounded-3xl glass-floating overflow-hidden transition-[width] duration-300 ease-out"
      style={{ width: expanded ? "min(720px, calc(100vw - 48px))" : "auto" }}
    >
      <div className="flex items-center gap-1 p-1">
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setPaused(!paused)}
          title={paused ? "Resume" : "Pause"}
        >
          {paused ? <Play size={14} /> : <Pause size={14} />}
        </Button>

        {!expanded && (
          <>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSpeed(speed === 32 ? 1 : speed * 2)}
              title="Cycle speed"
              className="min-w-[40px] tabular-nums px-2.5"
            >
              <FastForward size={12} />
              {speed}×
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => jumpForward(TICKS_PER_DAY)}
              title="Jump 1 day"
              className="px-2.5"
            >
              +1d
            </Button>
            <Button variant="ghost" size="icon" onClick={reset} title="Reset">
              <RotateCcw size={13} />
            </Button>
            <span className="mx-2 h-4 w-px bg-white/10" />
            <span className="text-[10.5px] tabular-nums text-[var(--color-fg-faint)] mr-2 ml-0.5">
              day {day}
            </span>
          </>
        )}

        {expanded && (
          <>
            <span className="ml-2 text-[11.5px] tabular-nums text-[var(--color-fg)]">
              Day {sliderDay} / {totalDays - 1}
            </span>
            <span className="text-[11px] text-[var(--color-fg-faint)] ml-2">
              {dateLabel}
            </span>
            <span className="flex-1" />
          </>
        )}

        <Button
          variant="ghost"
          size="icon"
          onClick={() => setExpanded(!expanded)}
          title={expanded ? "Collapse timeline" : "Expand timeline"}
        >
          {expanded ? <ChevronDown size={13} /> : <ChevronUp size={13} />}
        </Button>

        {!expanded && (
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setCommandPaletteOpen(true)}
            title="Command palette (⌘K)"
          >
            <Command size={13} />
          </Button>
        )}
      </div>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
            className="px-4 pb-3 overflow-hidden"
          >
            <div className="pt-2 pb-2">
              <input
                type="range"
                min={0}
                max={totalDays - 1}
                value={sliderDay}
                onChange={onScrubInput}
                onPointerUp={onScrubRelease}
                onPointerCancel={onScrubRelease}
                onBlur={onScrubRelease}
                className="timeline-scrub w-full h-1 rounded-full appearance-none bg-white/[0.10] accent-[var(--color-accent)] cursor-pointer"
                style={{
                  background: `linear-gradient(to right, var(--color-accent) 0%, var(--color-accent) ${fillPct}%, rgba(255,255,255,0.10) ${fillPct}%, rgba(255,255,255,0.10) 100%)`,
                }}
                aria-label="Scrub simulation timeline"
              />
              <div className="flex justify-between text-[10px] text-[var(--color-fg-faint)] mt-1.5 tabular-nums">
                <span>0d</span>
                <span>{Math.round(totalDays * 0.25)}d</span>
                <span>{Math.round(totalDays * 0.5)}d</span>
                <span>{Math.round(totalDays * 0.75)}d</span>
                <span>{totalDays}d</span>
              </div>
            </div>

            <div className="flex items-center justify-center gap-1 mt-2">
              <Button
                variant="ghost" size="sm"
                onClick={() => jumpForward(-7 * TICKS_PER_DAY)}
                title="-1 week" className="px-2 gap-1"
              >
                <SkipBack size={11} />1w
              </Button>
              <Button
                variant="ghost" size="sm"
                onClick={() => jumpForward(-TICKS_PER_DAY)}
                title="-1 day" className="px-2"
              >
                -1d
              </Button>
              <Button
                variant="ghost" size="sm"
                onClick={() => setPaused(!paused)}
                title={paused ? "Resume" : "Pause"} className="px-3"
              >
                {paused ? <Play size={12} /> : <Pause size={12} />}
              </Button>
              <Button
                variant="ghost" size="sm"
                onClick={() => jumpForward(TICKS_PER_DAY)}
                title="+1 day" className="px-2"
              >
                +1d
              </Button>
              <Button
                variant="ghost" size="sm"
                onClick={() => jumpForward(7 * TICKS_PER_DAY)}
                title="+1 week" className="px-2 gap-1"
              >
                1w<SkipForward size={11} />
              </Button>
              <span className="mx-2 h-4 w-px bg-white/10" />
              <Button variant="ghost" size="icon" onClick={reset} title="Reset">
                <RotateCcw size={13} />
              </Button>
              <Button
                variant="ghost" size="icon"
                onClick={() => setCommandPaletteOpen(true)}
                title="Command palette (⌘K)"
              >
                <Command size={13} />
              </Button>
            </div>

            <div className="flex items-center justify-center gap-1 mt-3">
              <span className="text-[10px] uppercase tracking-[0.18em] text-[var(--color-fg-faint)] mr-2">
                Speed
              </span>
              {SPEED_STEPS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setSpeed(s)}
                  className={`px-2.5 py-1 rounded-full text-[11px] tabular-nums transition-colors ${
                    s === speed
                      ? "bg-white/15 text-[var(--color-fg)]"
                      : "bg-white/[0.04] text-[var(--color-fg-muted)] hover:bg-white/[0.08]"
                  }`}
                >
                  {s}×
                </button>
              ))}
            </div>

            <div className="flex items-center justify-center gap-3 mt-3 text-[10px] text-[var(--color-fg-faint)]">
              <span><Kbd>←</Kbd> <Kbd>→</Kbd> day</span>
              <span><Kbd>⇧</Kbd>+<Kbd>←</Kbd> <Kbd>→</Kbd> week</span>
              <span><Kbd>Space</Kbd> play / pause</span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
