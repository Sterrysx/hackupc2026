import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "ghost" | "subtle" | "outline";
  size?: "sm" | "md" | "icon" | "iconLg";
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = "subtle", size = "md", ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-full",
        "font-medium tracking-tight select-none",
        "transition-all duration-200 ease-out",
        "disabled:opacity-40 disabled:pointer-events-none",
        size === "sm"     && "h-8 px-3 text-[12.5px]",
        size === "md"     && "h-9 px-4 text-[13px]",
        size === "icon"   && "h-9 w-9",
        size === "iconLg" && "h-11 w-11",
        variant === "primary" &&
          "bg-[var(--color-fg)] text-[var(--color-bg)] hover:opacity-90 active:scale-[0.98]",
        variant === "subtle" &&
          "bg-white/[0.06] text-[var(--color-fg)] hover:bg-white/[0.10]",
        variant === "outline" &&
          "border border-[var(--color-border-strong)] text-[var(--color-fg)] hover:bg-white/[0.06]",
        variant === "ghost" &&
          "text-[var(--color-fg-muted)] hover:text-[var(--color-fg)] hover:bg-white/[0.06]",
        className,
      )}
      {...props}
    />
  );
});
