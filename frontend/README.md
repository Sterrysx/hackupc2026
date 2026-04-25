# Aether — Frontend

Operator dashboard for the HP Metal Jet S100 Digital Twin (HackUPC 2026).

This is **Phase 1 only**: a clean, live dashboard powered by a synthetic mock-data
service that simulates what the backend, ML, and RAG teammates will eventually
publish. The data contract lives in `src/types/telemetry.ts` and intentionally
mirrors the pydantic schemas the backend will expose, so when the FastAPI is up
the swap is mechanical.

## Quick start

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

## Stack

| Concern             | Tool                          |
| ------------------- | ----------------------------- |
| Build / HMR         | Vite + React 19 + TypeScript  |
| Styling             | Tailwind v4 (Vite plugin)     |
| Animation           | Framer Motion                 |
| State               | Zustand                       |
| Charts              | Custom SVG sparklines         |
| Icons               | lucide-react                  |
| Command palette     | cmdk                          |

No shadcn CLI; primitives are hand-rolled in `src/components/ui/` so the visual
language is fully ours.

## Architecture

```
src/
├── types/telemetry.ts        # Data contract (mirrors backend pydantic)
├── lib/
│   ├── mockData.ts           # Synthetic state + forecasts + degradation curves
│   ├── alerts.ts             # Dual-trigger alert engine (current + predictive)
│   ├── rag.ts                # Mock RAG agent — every reply cites telemetry
│   └── cn.ts                 # Tailwind class merger
├── store/twin.ts             # Single Zustand store driving the whole UI
└── components/
    ├── Header.tsx            # Heartbeat + sim controls
    ├── FailureRibbon.tsx     # Top-of-page urgency strip
    ├── MetricsGrid.tsx       # Components grouped by subsystem
    ├── MetricTile.tsx        # Tile w/ predictive halo + sparkline
    ├── HealthRing.tsx        # SVG ring (current + forecast)
    ├── Sparkline.tsx         # Tiny inline trend chart
    ├── AlertsPanel.tsx       # Sorted active alerts feed
    ├── DriversCard.tsx       # Ambient/humidity/load drivers
    ├── ChatPanel.tsx         # Aether RAG chat with citation chips
    ├── ComponentDrawer.tsx   # Slide-in detail view (Apple-style reveal)
    ├── CommandPalette.tsx    # ⌘K palette
    └── ui/                   # Card, Button, Badge primitives
```

## Mock data → real backend

When the FastAPI is up, replace the public functions in `src/lib/mockData.ts`
with `fetch()` calls to the equivalent endpoints. Suggested mapping:

| Mock function              | Suggested endpoint                          |
| -------------------------- | ------------------------------------------- |
| `snapshotAtTick(tick)`     | `GET /api/snapshot?tick=...`                |
| `healthHistory(id, ...)`   | `GET /api/components/{id}/history?window=…` |
| `answer(prompt, snap)`     | `POST /api/rag` with `{prompt}`             |

Every consumer reads through `src/store/twin.ts`, so swapping the data layer
doesn't ripple into components.

## Wow features (Phase 1)

- **Predictive halo** — every tile shows current + 45-min forecast in a single ring.
- **Time-to-failure ribbon** — only appears when something needs attention.
- **Heartbeat header dot** — pulses with the simulation tick; goes still when paused.
- **Grounded chat citations** — every assistant reply chips its evidence; hover a chip to highlight the source component.
- **⌘K command palette** — jump to any component, run "what-if" jumps, or ask Aether.
- **Apple-style reveal** — clean tile by default; click → side drawer with raw metrics, predictive rationale, and history.

## Roadmap

- [x] Phase 1 — Synthetic data + clean dashboard
- [ ] Phase 2 — 2D interactive printer schematic with click-to-zoom popovers
- [ ] Phase 3 — 3D model with heatmap overlays (Three.js / R3F)
