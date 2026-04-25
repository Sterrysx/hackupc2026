import { useEffect, useState } from "react";
import { useTwin } from "@/store/twin";
import { Header } from "@/components/Header";
import { FailureRibbon } from "@/components/FailureRibbon";
import { MetricsGrid } from "@/components/MetricsGrid";
import { AlertsPanel } from "@/components/AlertsPanel";
import { DriversCard } from "@/components/DriversCard";
import { ChatPanel } from "@/components/ChatPanel";
import { FloatingChatButton } from "@/components/FloatingChatButton";
import { CommandPalette } from "@/components/CommandPalette";
import { ComponentDrawer } from "@/components/ComponentDrawer";
import { SchematicView } from "@/views/SchematicView";

type View = "dashboard" | "schematic";

function viewFromHash(): View {
  if (typeof window === "undefined") return "dashboard";
  return window.location.hash === "#schematic" ? "schematic" : "dashboard";
}

/**
 * Top-level shell. Two views, hash-routed:
 *   /            → dashboard (Phase 1)
 *   /#schematic  → interactive 2D schematic (Phase 2, in progress)
 */
export default function App() {
  const advance = useTwin((s) => s.advance);
  const [view, setView] = useState<View>(viewFromHash);

  useEffect(() => {
    const id = setInterval(() => advance(), 1000);
    return () => clearInterval(id);
  }, [advance]);

  useEffect(() => {
    const onHash = () => setView(viewFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  if (view === "schematic") return <SchematicView />;

  return (
    <div className="min-h-screen flex flex-col text-[var(--color-fg)]">
      <Header />

      <main className="flex-1">
        <div className="max-w-[1100px] mx-auto px-10 py-16 flex flex-col gap-16">
          <Hero />
          <FailureRibbon />
          <MetricsGrid />
          <AlertsPanel />
          <DriversCard />
          <Footer />
        </div>
      </main>

      <ChatPanel />
      <FloatingChatButton />
      <CommandPalette />
      <ComponentDrawer />
    </div>
  );
}

function Hero() {
  const { snapshot, alerts } = useTwin();
  const failed = snapshot.components.filter((c) => c.status === "FAILED").length;
  const critical = snapshot.components.filter((c) => c.status === "CRITICAL").length;
  const degraded = snapshot.components.filter((c) => c.status === "DEGRADED").length;
  const healthy = snapshot.components.length - failed - critical - degraded;
  const avgHealth = Math.round(
    (snapshot.components.reduce((a, c) => a + c.healthIndex, 0) / snapshot.components.length) * 100,
  );

  let headline: string;
  let supporting: string;

  if (failed) {
    headline = `${failed} component${failed === 1 ? "" : "s"} offline`;
    supporting = "Immediate inspection recommended.";
  } else if (critical) {
    headline = "Attention needed";
    supporting = `${critical} critical · ${degraded} degraded · forecasting next ${snapshot.forecastHorizonMin} min.`;
  } else if (degraded) {
    headline = "All systems running";
    supporting = `${degraded} component${degraded === 1 ? "" : "s"} degraded — schedule maintenance soon.`;
  } else if (alerts.length > 0) {
    headline = "All systems running";
    supporting = `${alerts.length} predictive watch${alerts.length === 1 ? "" : "es"} active.`;
  } else {
    headline = "All systems healthy";
    supporting = `${healthy} of ${snapshot.components.length} components nominal · average health ${avgHealth}%.`;
  }

  return (
    <section className="flex flex-col gap-3">
      <p className="text-[11px] uppercase tracking-[0.22em] text-[var(--color-fg-faint)]">
        Operator overview
      </p>
      <h1 className="text-[40px] sm:text-[48px] font-medium tracking-[-0.02em] leading-[1.05] text-[var(--color-fg)]">
        {headline}
      </h1>
      <p className="text-[16px] text-[var(--color-fg-muted)] max-w-prose">
        {supporting}
      </p>
    </section>
  );
}

function Footer() {
  return (
    <footer className="pt-10 mt-4 border-t border-[var(--color-border)] flex items-center justify-between text-[10.5px] uppercase tracking-[0.18em] text-[var(--color-fg-faint)]">
      <span>Phase 1 · Synthetic telemetry</span>
      <a
        href="#schematic"
        className="text-[var(--color-fg-faint)] hover:text-[var(--color-fg-muted)] transition-colors"
      >
        Schematic preview →
      </a>
    </footer>
  );
}
