import type { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {
  width?: string | number;
  height?: string | number;
}

/** Shimmering placeholder for not-yet-loaded content. */
export function Skeleton({
  className,
  width,
  height = "0.85em",
  style,
  ...props
}: SkeletonProps) {
  return (
    <div
      className={cn("rounded-full overflow-hidden", className)}
      style={{
        background:
          "linear-gradient(90deg, oklch(1 0 0 / 0.04) 0%, oklch(1 0 0 / 0.13) 50%, oklch(1 0 0 / 0.04) 100%)",
        backgroundSize: "200% 100%",
        animation: "shimmer 1.6s ease-in-out infinite",
        width: typeof width === "number" ? `${width}px` : width ?? "100%",
        height: typeof height === "number" ? `${height}px` : height,
        ...style,
      }}
      {...props}
    />
  );
}

/** Three-dot typing indicator — used inside the chat while the RAG is "thinking". */
export function ChatThinking() {
  return (
    <div
      role="status"
      aria-label="Aether is thinking"
      className="inline-flex items-center gap-1.5 px-3.5 py-3 rounded-[20px] rounded-bl-md bg-white/[0.06]"
    >
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="block h-1.5 w-1.5 rounded-full bg-[var(--color-fg-muted)]"
          style={{
            animation: "softPulse 1.2s ease-in-out infinite",
            animationDelay: `${i * 0.18}s`,
          }}
        />
      ))}
    </div>
  );
}
