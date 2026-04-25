import type { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";
import type { AlertSeverity, OperationalStatus } from "@/types/telemetry";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: "neutral" | "ok" | "info" | "warn" | "crit";
  size?: "xs" | "sm" | "md";
  /** When true, render as a soft pill with a dot — used for status indicators. */
  withDot?: boolean;
}

export function Badge({
  className,
  tone = "neutral",
  size = "sm",
  withDot = false,
  children,
  ...props
}: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full font-medium tracking-tight whitespace-nowrap",
        "border border-transparent",
        size === "xs" && "px-2 py-0.5 text-[10.5px]",
        size === "sm" && "px-2.5 py-[3px] text-[11px]",
        size === "md" && "px-3 py-1 text-[12px]",
        toneClasses(tone),
        className,
      )}
      {...props}
    >
      {withDot && <span className={cn("h-1.5 w-1.5 rounded-full", dotClass(tone))} />}
      {children}
    </span>
  );
}

function toneClasses(tone: NonNullable<BadgeProps["tone"]>): string {
  // Soft, low-saturation pills — Apple system label feel.
  switch (tone) {
    case "ok":
      return "bg-[oklch(0.78_0.10_155/0.14)] text-[oklch(0.92_0.10_155)]";
    case "info":
      return "bg-[oklch(0.78_0.10_240/0.14)] text-[oklch(0.92_0.10_240)]";
    case "warn":
      return "bg-[oklch(0.83_0.12_75/0.16)]  text-[oklch(0.93_0.12_75)]";
    case "crit":
      return "bg-[oklch(0.72_0.13_25/0.18)]  text-[oklch(0.88_0.13_25)]";
    case "neutral":
    default:
      return "bg-white/[0.06] text-[var(--color-fg-muted)]";
  }
}

function dotClass(tone: NonNullable<BadgeProps["tone"]>): string {
  switch (tone) {
    case "ok":   return "bg-[var(--color-ok)]";
    case "info": return "bg-[var(--color-info)]";
    case "warn": return "bg-[var(--color-warn)]";
    case "crit": return "bg-[var(--color-crit)]";
    case "neutral":
    default:     return "bg-white/40";
  }
}

/* ── Status / severity → tone + display label helpers ──────────────────── */

export function statusToTone(status: OperationalStatus): NonNullable<BadgeProps["tone"]> {
  switch (status) {
    case "FUNCTIONAL": return "ok";
    case "DEGRADED":   return "warn";
    case "CRITICAL":   return "crit";
    case "FAILED":     return "crit";
  }
}

export function statusLabel(status: OperationalStatus): string {
  switch (status) {
    case "FUNCTIONAL": return "Healthy";
    case "DEGRADED":   return "Warning";
    case "CRITICAL":   return "Critical";
    case "FAILED":     return "Failed";
  }
}

export function severityToTone(s: AlertSeverity): NonNullable<BadgeProps["tone"]> {
  switch (s) {
    case "INFO":     return "info";
    case "WARNING":  return "warn";
    case "CRITICAL": return "crit";
  }
}

export function severityLabel(s: AlertSeverity): string {
  switch (s) {
    case "INFO":     return "Info";
    case "WARNING":  return "Warning";
    case "CRITICAL": return "Critical";
  }
}
