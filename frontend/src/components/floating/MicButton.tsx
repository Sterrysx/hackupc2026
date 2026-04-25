import { motion, AnimatePresence } from "framer-motion";
import { AlertCircle, Loader2, Mic, Square } from "lucide-react";
import { cn } from "@/lib/cn";
import { useVoiceCapture } from "@/lib/voice";

interface MicButtonProps {
  onTranscript: (text: string) => void;
  size?: "sm" | "md";
  className?: string;
  hint?: string;
}

/**
 * MicButton — voice-input affordance that wraps `useVoiceCapture` and the
 * `/stt/transcribe` endpoint. Tap to record, tap again to stop. The
 * transcript is handed back to the parent (usually it gets appended to a
 * draft input rather than auto-sent — gives the user a moment to verify).
 */
export function MicButton({ onTranscript, size = "md", className, hint }: MicButtonProps) {
  const { state, errorMessage, isSupported, toggle } = useVoiceCapture({ onTranscript });

  if (!isSupported) return null;

  const dims = size === "sm" ? "h-7 w-7" : "h-9 w-9";
  const iconSize = size === "sm" ? 11 : 14;

  const titles: Record<typeof state, string> = {
    idle: hint ?? "Talk to Aether",
    recording: "Recording — tap to stop",
    transcribing: "Transcribing…",
    error: errorMessage ?? "Voice error",
  };

  const isHot = state === "recording";
  const isErr = state === "error";

  return (
    <button
      type="button"
      onClick={() => void toggle()}
      title={titles[state]}
      aria-label={titles[state]}
      aria-pressed={isHot}
      data-state={state}
      className={cn(
        "relative inline-flex items-center justify-center rounded-full transition-colors duration-200",
        dims,
        isHot
          ? "bg-[oklch(0.72_0.13_25/0.18)] text-[oklch(0.86_0.10_25)]"
          : isErr
          ? "bg-[oklch(0.72_0.13_25/0.14)] text-[oklch(0.86_0.10_25)]"
          : "text-[var(--color-fg-muted)] hover:text-[var(--color-fg)] hover:bg-white/[0.10]",
        className,
      )}
    >
      <AnimatePresence mode="wait" initial={false}>
        {state === "idle" && (
          <motion.span
            key="mic"
            initial={{ opacity: 0, scale: 0.85 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.85 }}
            transition={{ duration: 0.14 }}
          >
            <Mic size={iconSize} />
          </motion.span>
        )}
        {state === "recording" && (
          <motion.span
            key="rec"
            initial={{ opacity: 0, scale: 0.85 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.85 }}
            transition={{ duration: 0.14 }}
          >
            <Square size={iconSize - 2} fill="currentColor" />
          </motion.span>
        )}
        {state === "transcribing" && (
          <motion.span
            key="tx"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.14 }}
            className="animate-spin"
          >
            <Loader2 size={iconSize} />
          </motion.span>
        )}
        {state === "error" && (
          <motion.span
            key="err"
            initial={{ opacity: 0, scale: 0.85 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.85 }}
            transition={{ duration: 0.14 }}
          >
            <AlertCircle size={iconSize} />
          </motion.span>
        )}
      </AnimatePresence>

      {/* Pulse ring while recording — keeps the affordance lively without being noisy. */}
      {isHot && (
        <span
          className="absolute inset-0 rounded-full pointer-events-none"
          style={{
            border: "1.5px solid oklch(0.72 0.13 25 / 0.6)",
            animation: "softPulse 1.2s ease-in-out infinite",
          }}
          aria-hidden
        />
      )}
    </button>
  );
}
