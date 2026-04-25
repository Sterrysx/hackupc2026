import { forwardRef } from "react";
import type { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: "surface" | "glass" | "raised";
  interactive?: boolean;
}

/**
 * Card primitive — squircle, hairline border, no harsh shadows.
 *  - surface: solid muted grey, used inside glass containers.
 *  - glass:   default for top-level cards over the page background.
 *  - raised:  used very sparingly when one card needs to sit "above" the rest.
 */
export const Card = forwardRef<HTMLDivElement, CardProps>(function Card(
  { className, variant = "glass", interactive = false, ...props },
  ref,
) {
  return (
    <div
      ref={ref}
      className={cn(
        "rounded-3xl transition-all duration-300 ease-out",
        variant === "surface" &&
          "bg-[var(--color-bg-elevated)] border border-[var(--color-border)]",
        variant === "glass" && "glass",
        variant === "raised" && "glass-strong",
        interactive &&
          "cursor-pointer hover:border-[var(--color-border-strong)] hover:bg-[oklch(0.30_0.003_260/0.62)]",
        className,
      )}
      {...props}
    />
  );
});
