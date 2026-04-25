import { useMemo } from "react";
import { LayoutGroup } from "framer-motion";
import { useTwin } from "@/store/twin";
import { MetricTile } from "@/components/MetricTile";
import type { ComponentState } from "@/types/telemetry";

const SUBSYSTEM_ORDER: ComponentState["subsystem"][] = ["recoating", "printhead", "thermal"];

export function MetricsGrid() {
  const { snapshot, highlightComponentId, selectComponent } = useTwin();

  const grouped = useMemo(
    () =>
      SUBSYSTEM_ORDER.map((sub) => ({
        subsystem: sub,
        components: snapshot.components.filter((c) => c.subsystem === sub),
      })),
    [snapshot],
  );

  return (
    <section className="flex flex-col gap-12">
      <header className="flex items-end justify-between gap-4">
        <div>
          <h2 className="text-[22px] font-medium tracking-tight text-[var(--color-fg)]">
            Components
          </h2>
          <p className="text-[13px] text-[var(--color-fg-muted)] mt-1.5">
            Tap a component to see its live metrics, history, and forecast.
          </p>
        </div>
      </header>

      <LayoutGroup>
        <div className="flex flex-col gap-10">
          {grouped.map(({ subsystem, components }) => (
            <div key={subsystem} className="flex flex-col gap-4">
              <div className="flex items-center gap-3">
                <span className="text-[10.5px] uppercase tracking-[0.18em] text-[var(--color-fg-faint)]">
                  {label(subsystem)}
                </span>
                <span className="h-px flex-1 bg-[var(--color-border)]" />
              </div>
              <div className="grid gap-3 grid-cols-1 lg:grid-cols-2">
                {components.map((c) => {
                  const f = snapshot.forecasts.find((x) => x.id === c.id)!;
                  return (
                    <MetricTile
                      key={c.id}
                      component={c}
                      forecast={f}
                      highlighted={highlightComponentId === c.id}
                      onClick={() => selectComponent(c.id)}
                    />
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </LayoutGroup>
    </section>
  );
}

function label(s: ComponentState["subsystem"]): string {
  switch (s) {
    case "recoating": return "Recoating system";
    case "printhead": return "Printhead array";
    case "thermal":   return "Thermal control";
  }
}
