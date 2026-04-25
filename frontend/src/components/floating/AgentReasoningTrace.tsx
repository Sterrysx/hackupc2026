import { useId, useState } from "react";
import { ChevronDown, Cpu, Sparkles } from "lucide-react";
import type { AgentReasoningStep } from "@/types/telemetry";
import { cn } from "@/lib/cn";

function kindStyles(kind: string): string {
  const k = kind.toLowerCase();
  if (k === "tool_call" || k === "tool") return "border-amber-500/30 bg-amber-500/[0.07] text-amber-200/90";
  if (k === "tool_result" || k === "result") return "border-sky-500/30 bg-sky-500/[0.07] text-sky-100/90";
  if (k === "retrieval" || k === "context") return "border-emerald-500/30 bg-emerald-500/[0.07] text-emerald-100/90";
  if (k === "assistant" || k === "model") return "border-white/15 bg-white/[0.04] text-[var(--color-fg)]";
  if (k === "user") return "border-white/12 bg-white/[0.03] text-[var(--color-fg-muted)]";
  if (k === "system") return "border-white/10 bg-black/20 text-[var(--color-fg-muted)]";
  if (k === "meta" || k === "validation") return "border-violet-500/30 bg-violet-500/[0.08] text-violet-100/90";
  if (k === "structured" || k === "report_draft")
    return "border-fuchsia-500/30 bg-fuchsia-500/[0.06] text-fuchsia-100/85";
  if (k === "error") return "border-red-500/40 bg-red-500/[0.08] text-red-200/90";
  return "border-white/10 bg-white/[0.02] text-[var(--color-fg-muted)]";
}

/**
 * Collapsible step-by-step trace from the LangGraph agent (tools, model, validation).
 * Shown under assistant messages so the operator can see the system is working.
 */
export function AgentReasoningTrace({ steps }: { steps: AgentReasoningStep[] }) {
  const [open, setOpen] = useState(true);
  const id = useId();
  if (!steps.length) return null;

  return (
    <div className="w-full max-w-[min(100%,32rem)]">
      <button
        type="button"
        id={`${id}-btn`}
        aria-expanded={open}
        aria-controls={`${id}-panel`}
        onClick={() => setOpen((o) => !o)}
        className="group flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-[11px] text-[var(--color-fg-muted)] transition hover:bg-white/[0.04] hover:text-[var(--color-fg)]"
      >
        <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-cyan-500/15 text-cyan-200/90">
          <Cpu className="h-3.5 w-3.5" aria-hidden />
        </span>
        <span className="font-medium tracking-wide">Agent activity</span>
        <span className="ml-auto tabular-nums text-[10px] text-[var(--color-fg-faint)]">
          {steps.length} step{steps.length === 1 ? "" : "s"}
        </span>
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-[var(--color-fg-faint)] transition-transform",
            open && "rotate-180",
          )}
        />
      </button>
      {open && (
        <div
          id={`${id}-panel`}
          role="region"
          aria-labelledby={`${id}-btn`}
          className="mt-1.5 max-h-72 space-y-2 overflow-y-auto rounded-[14px] border border-white/[0.08] bg-black/25 px-2.5 py-2.5"
        >
          {steps.map((s, i) => (
            <div
              key={`${i}-${s.label}`}
              className={cn(
                "rounded-lg border px-2.5 py-2 text-[11px] leading-snug",
                kindStyles(s.kind),
              )}
            >
              <div className="mb-1 flex items-center gap-1.5 text-[9.5px] font-semibold uppercase tracking-[0.12em] opacity-80">
                <Sparkles className="h-2.5 w-2.5 opacity-60" aria-hidden />
                <span className="truncate">{s.label}</span>
                <span className="ml-auto font-mono text-[8px] font-normal normal-case tracking-normal opacity-50">
                  {s.kind}
                </span>
              </div>
              <pre className="whitespace-pre-wrap break-words font-mono text-[10.5px] opacity-95 [color:inherit]">
                {s.content}
              </pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
