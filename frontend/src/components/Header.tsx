import { useEffect, useState } from "react";
import { Pause, Play, RotateCcw, FastForward } from "lucide-react";
import { useTwin } from "@/store/twin";
import { Button } from "@/components/ui/Button";

/**
 * Header — quiet brand bar.
 *  - Heartbeat dot is small, soft, no glow.
 *  - Sim controls live in a single grouped pill.
 *  - Chat lives elsewhere (floating button); no toggle here.
 *  - The status summary moves out of the header into the page hero.
 */
export function Header() {
  const { paused, speed, setPaused, setSpeed, reset, jumpForward, snapshot } = useTwin();
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const i = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(i);
  }, []);

  return (
    <header className="sticky top-0 z-30 glass-strong">
      <div className="max-w-[1100px] mx-auto flex items-center justify-between gap-6 px-10 h-16">
        <div className="flex items-center gap-3">
          <Heartbeat paused={paused} />
          <div className="leading-tight">
            <div className="text-[14px] font-medium tracking-tight text-[var(--color-fg)]">
              Aether
            </div>
            <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--color-fg-faint)]">
              HP Metal Jet S100
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1">
          <span className="hidden sm:block text-[11.5px] tabular-nums text-[var(--color-fg-faint)] mr-3">
            {now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            <span className="mx-1.5 text-[var(--color-fg-faint)]">·</span>
            tick {snapshot.tick}
          </span>

          <div className="flex items-center gap-0.5 rounded-full bg-white/[0.04] p-0.5">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setPaused(!paused)}
              title={paused ? "Resume" : "Pause"}
            >
              {paused ? <Play size={15} /> : <Pause size={15} />}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSpeed(speed === 32 ? 1 : speed * 2)}
              title="Cycle speed"
              className="min-w-[40px] tabular-nums"
            >
              <FastForward size={13} />
              {speed}×
            </Button>
            <Button variant="ghost" size="sm" onClick={() => jumpForward(120)} title="Jump 2 hours forward">
              +2h
            </Button>
            <Button variant="ghost" size="icon" onClick={reset} title="Reset">
              <RotateCcw size={14} />
            </Button>
          </div>
        </div>
      </div>
    </header>
  );
}

function Heartbeat({ paused }: { paused: boolean }) {
  return (
    <div className="relative flex items-center justify-center w-6 h-6">
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{
          background: paused ? "var(--color-fg-faint)" : "var(--color-ok)",
          animation: paused ? undefined : "softPulse 2.4s ease-in-out infinite",
        }}
      />
    </div>
  );
}
