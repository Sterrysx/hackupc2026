import { Pause, Play, RotateCcw, FastForward, Command } from "lucide-react";
import { useTwin } from "@/store/twin";
import { Button } from "@/components/ui/Button";

/**
 * Simulation controls — floating glass pill at bottom-centre.
 * Always visible (in both Immersive and Dashboard modes) so the operator
 * can pause / scrub time without leaving the canvas.
 */
export function SimControls() {
  const {
    paused,
    speed,
    setPaused,
    setSpeed,
    jumpForward,
    reset,
    setCommandPaletteOpen,
    snapshot,
  } = useTwin();

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-30 flex items-center gap-1 p-1 rounded-full glass-floating">
      <Button
        variant="ghost"
        size="icon"
        onClick={() => setPaused(!paused)}
        title={paused ? "Resume" : "Pause"}
      >
        {paused ? <Play size={14} /> : <Pause size={14} />}
      </Button>
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
      <Button variant="ghost" size="sm" onClick={() => jumpForward(120)} title="Jump 2 hours" className="px-2.5">
        +2h
      </Button>
      <Button variant="ghost" size="icon" onClick={reset} title="Reset">
        <RotateCcw size={13} />
      </Button>

      <span className="mx-2 h-4 w-px bg-white/10" />

      <span className="text-[10.5px] tabular-nums text-[var(--color-fg-faint)] mr-2 ml-0.5">
        tick {snapshot.tick}
      </span>

      <Button
        variant="ghost"
        size="icon"
        onClick={() => setCommandPaletteOpen(true)}
        title="Command palette (⌘K)"
      >
        <Command size={13} />
      </Button>
    </div>
  );
}
